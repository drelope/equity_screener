"""
Nightly dividend-equity ETL Airflow DAG.

Runs ``python -m scripts.run_full_etl`` (stages 0-6) once per day from the
checked-in virtualenv. Adjust PROJECT_ROOT / PYTHON for your host paths. See
docs/deployment-runbook.md §5 for setup and the Azure Functions alternative.

Requires Airflow mounted with the data-engineering repo path; install only at
deployment time (Airflow stays optional for the local MVP).
"""

from datetime import datetime, timedelta
from pathlib import Path

from airflow.operators.python import PythonOperator

from airflow import DAG

PROJECT_ROOT = Path("/mnt/d/dividend_equity_crispdm_implementation/dividend_equity_crispdm")
PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python"

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

    result = subprocess.run(
        [str(PYTHON), "-m", "scripts.run_full_etl"],
        cwd=str(PROJECT_ROOT),
        check=False,
    )
    if result.returncode != 0:
        sys.exit(result.returncode)


with DAG(
    dag_id="dividend_equity_nightly_etl",
    description="Nightly dividend-equity ETL: SEC EDGAR/XBRL + OpenBB -> raw -> features -> scores/rankings",
    start_date=datetime(2026, 1, 1),
    schedule_interval="0 3 * * *",
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
