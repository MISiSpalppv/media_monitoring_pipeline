import os
import subprocess
from pathlib import Path
import json

import psycopg
from airflow.sdk import dag, task
from pendulum import datetime

from src.load.postgres import load_publications


BASE_DIR = Path("/opt/airflow")
OUTPUT_FILE = "data/processed/irecommend_airflow.json"


@dag(
    dag_id="media_monitoring_elt",
    start_date=datetime(2026, 10, 30, tz="UTC"),
    schedule=None,
    catchup=False,
    tags=["media-monitoring", "elt"],
)
def media_monitoring_elt():
    @task
    def extract():
        command = [
            "python",
            "-m",
            "scrapy",
            "runspider",
            str(BASE_DIR / "src/extract/irecommend_spider.py"),
            "-O",
            str(BASE_DIR / OUTPUT_FILE),
            "-s",
            "LOG_LEVEL=INFO",
        ]

        subprocess.run(
            command,
            cwd=BASE_DIR,
            check=True,
        )

        output_path = BASE_DIR / OUTPUT_FILE
        publications = json.loads(output_path.read_text(encoding="utf-8"))

        if not publications:
            raise RuntimeError(
                "EXTRACT failed: Scrapy collected 0 publications. "
                "Check HTTP responses and spider logs."
            )

        print(f"Extracted publications: {len(publications)}")

        return OUTPUT_FILE

    @task
    def load_raw(file_path: str):
        return load_publications(file_path)

    @task
    def transform_staging(_loaded_count: int):
        sql = (BASE_DIR / "sql/002_staging.sql").read_text(
            encoding="utf-8"
        )

        with psycopg.connect(
            host=os.environ["POSTGRES_HOST"],
            dbname=os.environ["POSTGRES_DB"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
        ) as connection:
            connection.execute(sql)

        return "STAGING transformation completed"

    transform_staging(load_raw(extract()))


media_monitoring_elt()