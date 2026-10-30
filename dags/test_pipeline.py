from datetime import datetime

from airflow.sdk import dag, task


@dag(
    dag_id="test_pipeline",
    start_date=datetime(2026, 10, 1),
    schedule=None,
    catchup=False,
    tags=["test"],
)
def test_pipeline():

    @task
    def extract():
        print("Extract: collecting data")
        return {"source": "test", "records": 10}

    @task
    def transform(data):
        print(f"Transform: processing {data['records']} records")
        return data

    @task
    def load(data):
        print(f"Load: saving {data['records']} records")

    load(transform(extract()))


test_pipeline()