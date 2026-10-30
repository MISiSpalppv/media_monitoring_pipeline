import os

import psycopg

from src.config import PROJECT_ROOT


REQUIRED = ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")


def load_env():
    if all(os.getenv(key) for key in REQUIRED):
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

    missing = [key for key in REQUIRED if not os.getenv(key)]

    if missing:
        raise RuntimeError(
            f"Missing PostgreSQL environment variables: {missing}"
        )


def connect(**kwargs) -> psycopg.Connection:
    """Подключение к БД проекта. Локально host=localhost, в контейнере POSTGRES_HOST=postgres."""
    load_env()
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        **kwargs,
    )
