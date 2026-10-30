import json
from pathlib import Path

from psycopg.types.json import Jsonb

from src.config import PROJECT_ROOT
from src.db.connection import connect


# Одна команда на весь файл. Конфликт по (URL, хэш) означает, что такая
# версия публикации уже есть, и строка пропускается.
INSERT_RAW = """
    INSERT INTO raw.publications (
        source_id,
        run_id,
        source_url,
        publication_url,
        content_hash,
        payload,
        fetched_at
    )
    SELECT
        r ->> 'source_id',
        r ->> 'run_id',
        r ->> 'source_url',
        r ->> 'url',
        r ->> 'content_hash',
        r,
        (r ->> 'fetched_at')::TIMESTAMPTZ
    FROM jsonb_array_elements(%s) AS r
    ON CONFLICT (publication_url, content_hash) DO NOTHING
"""

TRANSFORM_STAGING = PROJECT_ROOT / "sql" / "transform" / "staging_publications.sql"


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_publications(conn, file_path: str | Path) -> int:
    """Загружает JSONL с публикациями в RAW. Возвращает число новых строк."""
    path = Path(file_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path

    records = read_jsonl(path)
    if not records:
        return 0

    return conn.execute(INSERT_RAW, (Jsonb(records),)).rowcount


def transform_staging(conn) -> int:
    """Обновляет STAGING из RAW. Возвращает число вставленных/изменённых строк."""
    sql = TRANSFORM_STAGING.read_text(encoding="utf-8")
    return conn.execute(sql).rowcount


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("file", help="JSONL с публикациями")
    args = parser.parse_args()

    with connect() as conn:
        count = load_publications(conn, args.file)
    print(f"Загружено новых записей в RAW: {count}")
