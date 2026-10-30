import json
import os
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_env():
    """Загружает переменные подключения из локального .env."""
    env_path = PROJECT_ROOT / ".env"

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_publications(file_path: str) -> int:
    """Загружает JSON-записи в RAW-слой PostgreSQL."""
    load_env()

    path = PROJECT_ROOT / file_path
    publications = json.loads(path.read_text(encoding="utf-8"))

    connection_params = {
        "host": "localhost",
        "port": 5432,
        "dbname": os.environ["POSTGRES_DB"],
        "user": os.environ["POSTGRES_USER"],
        "password": os.environ["POSTGRES_PASSWORD"],
    }

    query = """
        INSERT INTO raw.publications (
            source_url,
            publication_url,
            payload
        )
        VALUES (%s, %s, %s)
    """

    with psycopg.connect(**connection_params) as connection:
        with connection.cursor() as cursor:
            for publication in publications:
                cursor.execute(
                    query,
                    (
                        publication["source_url"],
                        publication["url"],
                        Jsonb(publication),
                    ),
                )

    return len(publications)


if __name__ == "__main__":
    count = load_publications(
        "data/processed/irecommend_batch_test.json"
    )
    print(f"Загружено записей в RAW: {count}")