"""Применяет sql/migrations/NNN_*.sql по порядку.

    python -m src.db.migrate          # применить новые
    python -m src.db.migrate --list   # показать состояние
"""
import argparse
import logging

from src.config import PROJECT_ROOT
from src.db.connection import connect


MIGRATIONS_DIR = PROJECT_ROOT / "sql" / "migrations"

log = logging.getLogger(__name__)


def applied_migrations(conn) -> set[str]:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS public.schema_migrations (
            name TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    rows = conn.execute("SELECT name FROM public.schema_migrations").fetchall()
    return {row[0] for row in rows}


def migrate(list_only: bool = False) -> list[str]:
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    applied_now = []

    with connect(autocommit=True) as conn:
        done = applied_migrations(conn)

        for path in files:
            if path.name in done:
                log.info("%s: already applied", path.name)
                continue
            if list_only:
                log.info("%s: pending", path.name)
                continue

            # каждая миграция в своей транзакции: при ошибке откатывается целиком
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT INTO public.schema_migrations (name) VALUES (%s)",
                    (path.name,),
                )
            log.info("%s: applied", path.name)
            applied_now.append(path.name)

    return applied_now


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    migrate(list_only=args.list)
