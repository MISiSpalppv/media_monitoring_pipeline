from datetime import timedelta

from airflow.exceptions import AirflowFailException
from airflow.sdk import dag, task
from pendulum import datetime

from src import pipeline


@dag(
    dag_id="media_monitoring_elt",
    start_date=datetime(2026, 10, 30, tz="UTC"),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    tags=["media-monitoring", "elt"],
)
def media_monitoring_elt():
    @task
    def start(**context) -> list[str]:
        run_id = pipeline.make_run_id(context["run_id"])
        return pipeline.start_run(run_id, airflow_run_id=context["run_id"])

    @task(
        retries=2,
        retry_delay=timedelta(minutes=1),
        retry_exponential_backoff=True,
        max_retry_delay=timedelta(minutes=10),
    )
    def extract(source_id: str, **context) -> str:
        run_id = pipeline.make_run_id(context["run_id"])
        summary = pipeline.extract_source(source_id, run_id, attempt=context["ti"].try_number)
        status, reason = summary["status"], summary.get("reason")

        if status == "success":
            return status
        # Страница загрузилась, но публикаций нет: повтор не поможет
        if status == "empty":
            raise AirflowFailException(f"{source_id}: empty, {reason}")
        # unavailable и failed могут быть временными, Airflow повторит задачу
        raise RuntimeError(f"{source_id}: {status}, {reason}")

    # Загрузка идёт, если хотя бы один источник успешен: какие именно,
    # load_run берёт из ops.source_runs. Если успешных нет, задача падает.
    @task(trigger_rule="all_done")
    def load_raw(**context) -> int:
        return pipeline.load_run(pipeline.make_run_id(context["run_id"]))

    @task
    def transform_staging(**context) -> int:
        return pipeline.transform_run(pipeline.make_run_id(context["run_id"]))

    @task
    def enrich_staging(**context) -> int:
        return pipeline.enrich_run(pipeline.make_run_id(context["run_id"]))

    @task
    def refresh_marts(**context) -> None:
        pipeline.refresh_marts(pipeline.make_run_id(context["run_id"]))

    @task(trigger_rule="all_done")
    def finish(**context) -> str:
        status = pipeline.finish_run(pipeline.make_run_id(context["run_id"]))
        if status == "failed":
            raise AirflowFailException("pipeline run failed, see ops.source_runs")
        return status

    sources = start()
    extracted = extract.expand(source_id=sources)
    (
        extracted
        >> load_raw()
        >> transform_staging()
        >> enrich_staging()
        >> refresh_marts()
        >> finish()
    )


media_monitoring_elt()
