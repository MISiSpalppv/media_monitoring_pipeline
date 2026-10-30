"""Разовая перезагрузка отзывов iRecommend, собранных старым пауком.

В старом файле дата лежит сырой строкой ("21 Май, 2026 - 17:10"), хэша нет.
Скрипт прогоняет записи через ту же нормализацию, что и паук, и загружает
их в RAW как новые версии. STAGING берёт последнюю версию по URL, поэтому
дублей там не появляется: строка просто получает нормализованную дату.

    python scripts/reload_legacy_irecommend.py
"""
import json
import logging
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import PROJECT_ROOT, get_source
from src.db.connection import connect
from src.extract.normalize import canonical_url, clean_text, collapse_spaces, content_hash, parse_date
from src.extract.publication import is_rejected, quality_flags
from src.load.postgres import load_publications, transform_staging
from src.models import Publication


LEGACY_FILE = PROJECT_ROOT / "data/processed/irecommend_batch_test.json"
RUN_ID = "legacy_reload"


def convert(record: dict, cfg: dict, fetched_at: datetime) -> Publication:
    url = canonical_url(record["url"])
    title = collapse_spaces(record.get("title"))
    author = collapse_spaces(record.get("author"))
    text = clean_text(record.get("text"))
    published = parse_date(record.get("published_at"), fetched_at, cfg["timezone"])
    published_at = published.isoformat() if published else None

    pub = Publication(
        source_id=cfg["id"],
        source_url=record["source_url"],
        url=url,
        # время сбора в старом файле не сохранялось
        fetched_at=fetched_at.isoformat(),
        run_id=RUN_ID,
        title=title,
        text=text,
        author=author,
        published_at=published_at,
        published_at_raw=record.get("published_at"),
        source_type=cfg.get("source_type"),
        extraction={"title": "css", "text": "css", "author": "css", "published_at": "css"},
        metadata={"legacy_file": LEGACY_FILE.name},
    )
    pub.content_hash = content_hash(url, title, author, text, published_at)
    pub.quality_flags = quality_flags(pub, published, fetched_at, cfg)
    return pub


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = get_source("irecommend")
    fetched_at = datetime.now(timezone.utc)

    records = json.loads(LEGACY_FILE.read_text(encoding="utf-8"))
    pubs = [convert(record, cfg, fetched_at) for record in records]
    accepted = [asdict(p) for p in pubs if not is_rejected(p)]
    logging.info("записей: %s, принято: %s", len(pubs), len(accepted))

    out = PROJECT_ROOT / "data/processed" / RUN_ID / "irecommend.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as f:
        for record in accepted:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    with connect() as conn:
        inserted = load_publications(conn, out)
        changed = transform_staging(conn)
    logging.info("RAW: новых строк %s, STAGING: изменено %s", inserted, changed)


if __name__ == "__main__":
    main()
