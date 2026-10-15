"""
Nightly dividend-equity ETL Airflow DAG.

Runs ``python -m scripts.run_full_etl`` (stages 0-6) once per day at
**03:00 America/New_York** (Eastern Time, DST-aware) from the checked-in
virtualenv. Adjust PROJECT_ROOT / PYTHON for your host paths. See
docs/deployment-runbook.md §5 for setup and the Azure Functions alternative.

Requires Airflow mounted with the data-engineering repo path; install only at
deployment time (Airflow stays optional for the local MVP).
"""

from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.operators.python import PythonOperator

from airflow import DAG

PROJECT_ROOT = Path("/mnt/d/dividend_equity_crispdm_implementation/dividend_equity_crispdm")
PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"
SCHEDULE_TZ = "America/New_York"

DEFAULT_ARGS = {
    "owner": "dividend-screener",
    "depends_on_past": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": True,
}


def run_full_etl() -> None:
    import subprocess
    import sys

    # Nightly accrual: stage 2 acquires dividends from DIVIDEND_LOOKBACK_START
    # (2025-01-01). After the PoC gate passes, switch to total history by
    # appending "--dividend-full-history" to the command below.
    result = subprocess.run(  # noqa: S603 - fixed argv, never a shell
        [str(PYTHON), "-m", "scripts.run_full_etl", "--trigger", "airflow"],
        cwd=str(PROJECT_ROOT),
        check=False,
    )
    if result.returncode != 0:
        sys.exit(result.returncode)


with DAG(
    dag_id="dividend_equity_nightly_etl",
    description="Nightly dividend-equity ETL: SEC EDGAR/XBRL + OpenBB -> raw -> features -> scores/rankings",
    start_date=pendulum.datetime(2026, 1, 1, tz=SCHEDULE_TZ),
    schedule_interval="0 3 * * *",
    timezone=SCHEDULE_TZ,
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["etl", "dividend"],
) as dag:
    run_etl = PythonOperator(
        task_id="run_full_etl",
        python_callable=run_full_etl,
        doc_md="Runs scripts.run_full_etl from the repo's virtualenv.",
    )

    run_etl
