"""Шаги пайплайна. DAG вызывает эти функции, их же можно запустить без Airflow:

    python -m src.pipeline --run-id manual_1
    python -m src.pipeline --run-id manual_1 --sources livejournal_5koleso
"""
import argparse
import json
import logging
import re
import subprocess
import sys
from pathlib import Path

from psycopg.types.json import Jsonb

from src.config import PROJECT_ROOT, load_sources
from src.db.connection import connect
from src.extract.spider import OUTPUT_ROOT
from src.load.postgres import load_publications, transform_staging
from src.transform import enrich


# Порядок важен: остальные витрины строятся из mart.publications
MART_VIEWS = (
    "mart.publications",
    "mart.daily_publications",
    "mart.category_weekly",
    "mart.publication_keywords",
    "mart.brand_mentions",
    "mart.source_health",
)


EXTRACT_TIMEOUT = 30 * 60

log = logging.getLogger(__name__)


def make_run_id(airflow_run_id: str) -> str:
    # run_id Airflow содержит ':' и '+', а он идёт в имя каталога
    return re.sub(r"[^\w.-]", "_", airflow_run_id)


def start_run(run_id: str, airflow_run_id: str | None = None,
              only: list[str] | None = None) -> list[str]:
    configs = load_sources()
    sources = [
        source_id for source_id, cfg in configs.items()
        if cfg["enabled"] and (not only or source_id in only)
    ]
    if not sources:
        raise ValueError("no enabled sources to run")

    with connect() as conn:
        sync_sources(conn, configs)
        conn.execute(
            """
            INSERT INTO ops.pipeline_runs (run_id, airflow_run_id, status, sources_total)
            VALUES (%s, %s, 'running', %s)
            ON CONFLICT (run_id) DO UPDATE
            SET status = 'running', sources_total = EXCLUDED.sources_total, finished_at = NULL
            """,
            (run_id, airflow_run_id, len(sources)),
        )
    return sources


def sync_sources(conn, configs: dict[str, dict]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO ops.sources (source_id, name, source_type, start_url, enabled)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (source_id) DO UPDATE SET
                name = EXCLUDED.name,
                source_type = EXCLUDED.source_type,
                start_url = EXCLUDED.start_url,
                enabled = EXCLUDED.enabled,
                updated_at = NOW()
            """,
            [
                (sid, cfg.get("name", sid), cfg.get("source_type"), cfg["start_urls"][0], cfg["enabled"])
                for sid, cfg in configs.items()
            ],
        )


def extract_source(source_id: str, run_id: str, attempt: int = 1) -> dict:
    """Запускает паука в отдельном процессе и пишет статус источника в ops.

    Отдельный процесс нужен из-за Twisted: реактор нельзя перезапустить
    в том же процессе, а воркер Airflow может выполнять задачи повторно.
    """
    summary_path = OUTPUT_ROOT / run_id / f"{source_id}.summary.json"
    summary_path.unlink(missing_ok=True)

    command = [sys.executable, "-m", "src.extract.spider",
               "--source", source_id, "--run-id", run_id]
    # Scrapy пишет лог в stderr, Airflow показывал бы его весь как ошибки
    result = subprocess.run(command, cwd=PROJECT_ROOT, timeout=EXTRACT_TIMEOUT,
                            stderr=subprocess.STDOUT)

    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    else:
        summary = {
            "source_id": source_id,
            "status": "failed",
            "reason": f"spider exited with code {result.returncode}, no summary",
        }

    output_file = OUTPUT_ROOT / run_id / f"{source_id}.jsonl"
    save_source_run(run_id, summary, attempt, output_file)
    return summary


def save_source_run(run_id: str, summary: dict, attempt: int, output_file: Path) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO ops.source_runs (
                run_id, source_id, status, reason, attempt,
                listing_pages_ok, publication_pages_ok, links_found,
                accepted, rejected, http_errors, other_errors,
                output_file, started_at, finished_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id, source_id) DO UPDATE SET
                status = EXCLUDED.status,
                reason = EXCLUDED.reason,
                attempt = EXCLUDED.attempt,
                listing_pages_ok = EXCLUDED.listing_pages_ok,
                publication_pages_ok = EXCLUDED.publication_pages_ok,
                links_found = EXCLUDED.links_found,
                accepted = EXCLUDED.accepted,
                rejected = EXCLUDED.rejected,
                http_errors = EXCLUDED.http_errors,
                other_errors = EXCLUDED.other_errors,
                output_file = EXCLUDED.output_file,
                started_at = EXCLUDED.started_at,
                finished_at = EXCLUDED.finished_at
            """,
            (
                run_id,
                summary["source_id"],
                summary["status"],
                summary.get("reason"),
                attempt,
                summary.get("listing_pages_ok", 0),
                summary.get("publication_pages_ok", 0),
                summary.get("links_found", 0),
                summary.get("accepted", 0),
                summary.get("rejected", 0),
                Jsonb(summary.get("http_errors", {})),
                Jsonb(summary.get("other_errors", {})),
                str(output_file.relative_to(PROJECT_ROOT)),
                summary.get("started_at"),
                summary.get("finished_at"),
            ),
        )


def load_run(run_id: str) -> int:
    """Загружает в RAW файлы источников со статусом success."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT source_id, output_file FROM ops.source_runs "
            "WHERE run_id = %s AND status = 'success'",
            (run_id,),
        ).fetchall()
        if not rows:
            raise RuntimeError(f"run {run_id}: no successful sources to load")

        total = 0
        for source_id, output_file in rows:
            inserted = load_publications(conn, output_file)
            conn.execute(
                "UPDATE ops.source_runs SET rows_inserted = %s "
                "WHERE run_id = %s AND source_id = %s",
                (inserted, run_id, source_id),
            )
            log.info("%s: в RAW добавлено %s строк", source_id, inserted)
            total += inserted

        conn.execute(
            "UPDATE ops.pipeline_runs SET rows_inserted = %s WHERE run_id = %s",
            (total, run_id),
        )
    return total


def transform_run(run_id: str) -> int:
    with connect() as conn:
        changed = transform_staging(conn)
        conn.execute(
            "UPDATE ops.pipeline_runs SET staging_rows = %s, transformed_at = NOW() "
            "WHERE run_id = %s",
            (changed, run_id),
        )
    log.info("STAGING: изменено строк %s", changed)
    return changed


def enrich_run(run_id: str) -> int:
    with connect() as conn:
        rows = enrich.run(conn)
        conn.execute(
            "UPDATE ops.pipeline_runs SET enriched_rows = %s WHERE run_id = %s",
            (rows, run_id),
        )
    return rows


def refresh_marts(run_id: str) -> None:
    with connect() as conn:
        for view in MART_VIEWS:
            conn.execute(f"REFRESH MATERIALIZED VIEW {view}")
        conn.execute(
            "UPDATE ops.pipeline_runs SET marts_refreshed_at = NOW() WHERE run_id = %s",
            (run_id,),
        )
    log.info("витрины обновлены: %s", len(MART_VIEWS))


def finish_run(run_id: str) -> str:
    """Итоговый бизнес-статус запуска.

    success - все источники success, STAGING и витрины обновлены;
    partial_success - хотя бы один источник success, STAGING и витрины обновлены;
    failed - остальное.
    """
    with connect() as conn:
        row = conn.execute(
            "SELECT sources_total, transformed_at, marts_refreshed_at "
            "FROM ops.pipeline_runs WHERE run_id = %s",
            (run_id,),
        ).fetchone()
        if row is None:
            log.error("run %s was not registered in ops.pipeline_runs", run_id)
            return "failed"
        total, transformed_at, marts_refreshed_at = row
        success = conn.execute(
            "SELECT COUNT(*) FROM ops.source_runs WHERE run_id = %s AND status = 'success'",
            (run_id,),
        ).fetchone()[0]

        if transformed_at is None or marts_refreshed_at is None or success == 0:
            status = "failed"
        elif success == total:
            status = "success"
        else:
            status = "partial_success"

        conn.execute(
            "UPDATE ops.pipeline_runs SET status = %s, sources_success = %s, finished_at = NOW() "
            "WHERE run_id = %s",
            (status, success, run_id),
        )
    log.info("run %s: %s (%s/%s sources)", run_id, status, success, total)
    return status


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--sources", help="через запятую; по умолчанию все включённые")
    args = parser.parse_args()

    only = args.sources.split(",") if args.sources else None
    sources = start_run(args.run_id, only=only)
    for source_id in sources:
        summary = extract_source(source_id, args.run_id)
        log.info("%s: %s %s", source_id, summary["status"], summary.get("reason") or "")

    try:
        load_run(args.run_id)
        transform_run(args.run_id)
        enrich_run(args.run_id)
        refresh_marts(args.run_id)
    finally:
        status = finish_run(args.run_id)

    if status == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
