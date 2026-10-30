import json
import os
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_env():
    required = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")

    if all(os.getenv(key) for key in required):
        return

    env_path = PROJECT_ROOT / ".env"

    if not env_path.is_file():
        raise RuntimeError(
            "PostgreSQL environment variables are missing "
            "and .env file was not found"
        )

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(
            key.strip(),
            value.strip().strip('"').strip("'"),
        )

    missing = [key for key in required if not os.getenv(key)]

    if missing:
        raise RuntimeError(
            f"Missing PostgreSQL environment variables: {missing}"
        )


def load_publications(file_path: str) -> int:
    """Загружает JSON-записи в RAW-слой PostgreSQL."""
    load_env()

    path = PROJECT_ROOT / file_path
    publications = json.loads(path.read_text(encoding="utf-8"))

    connection_params = {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
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