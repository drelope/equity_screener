"""The allowlist of operational tasks the web app may queue.

This module is the whole security boundary of the Operations page. A task is a catalog
key plus parameters; the command line is built here, from fixed module names and
validated values, and never from text a user typed. The worker rebuilds the argv from
this catalog and re-validates the parameters, so a row written to ``ops.tasks`` by
anything other than the app cannot run a command that is not listed below.

Rules the validation holds to:

* Unknown keys and unknown parameters are rejected, not ignored.
* Every value is coerced to a strict type or matched against a closed pattern. A free
  text parameter has to match a regular expression that excludes whitespace and a
  leading dash, so it cannot become a second flag.
* Argv elements are passed as a list; nothing is ever joined into a shell string.

Deliberately absent: ``scripts.resolve_ticker_conflict release`` (it deletes rows and
has its own confirmation and archive), migrations that apply changes, and anything
that takes a free-form command.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from datetime import date
from typing import Any

# One flag-safe token: no whitespace, cannot start with "-", bounded length.
_TICKERS = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,31}(,[A-Z0-9][A-Z0-9.\-]{0,31}){0,49}$")


@dataclass(frozen=True)
class Param:
    """One user-settable parameter and how it becomes argv.

    ``kind`` is ``int``, ``bool``, ``tickers`` or ``date``. A ``bool`` adds ``flag`` when
    true; the others add ``flag`` followed by the value, and only when a value is given.
    """

    name: str
    label: str
    kind: str
    flag: str
    help: str = ""
    default: Any = None
    minimum: int | None = None
    maximum: int | None = None


@dataclass(frozen=True)
class TaskDef:
    key: str
    title: str
    description: str
    module: str
    risk: str  # "read" | "write" | "heavy"
    timeout_seconds: int
    params: tuple[Param, ...] = ()
    fixed_args: tuple[str, ...] = ()
    #: The worker holds the pipeline lock around the task, so it cannot overlap a nightly
    #: or another exclusive task. run_full_etl takes the lock itself, so it is False there.
    exclusive: bool = False
    #: Exit codes that mean the task did its job. verify_nightly_run exits 1 to say
    #: "attention needed", which is a finding, not a failed task.
    ok_exit_codes: tuple[int, ...] = (0,)
    extra: dict = field(default_factory=dict)


CATALOG: dict[str, TaskDef] = {
    d.key: d
    for d in (
        TaskDef(
            key="verify_nightly",
            title="Verify the nightly run",
            description=(
                "Run the morning data-module audit and record it in audit.nightly_checks. "
                "Exit 1 means attention is needed, which is reported as a finding."
            ),
            module="scripts.verify_nightly_run",
            risk="read",
            timeout_seconds=600,
            ok_exit_codes=(0, 1),
        ),
        TaskDef(
            key="migrate_check",
            title="Check migrations are applied",
            description="Compare the migration ledger with the files on disk. Changes nothing.",
            module="scripts.migrate",
            fixed_args=("--check",),
            risk="read",
            timeout_seconds=300,
            ok_exit_codes=(0, 1),
        ),
        TaskDef(
            key="schema_drift",
            title="Check schema drift",
            description=(
                "Build a scratch database from the repository and diff it against the live "
                "catalog. Creates and drops a scratch database; reads no data."
            ),
            module="scripts.check_schema_drift",
            fixed_args=("--quiet",),
            risk="read",
            timeout_seconds=1800,
            ok_exit_codes=(0, 1),
        ),
        TaskDef(
            key="ticker_conflicts",
            title="Review ticker/CIK conflicts",
            description=(
                "Read-only: compare SEC's ticker file with the stored mappings and classify "
                "each conflict from SEC's per-issuer data. Releasing a conflict is a separate, "
                "deliberate command and is not available here."
            ),
            module="scripts.resolve_ticker_conflict",
            fixed_args=("review",),
            risk="read",
            timeout_seconds=900,
        ),
        TaskDef(
            key="build_features",
            title="Rebuild features",
            description=(
                "Rebuild model.features for the last N days of observations (upsert). The "
                "window must exceed 252 trading days or momentum and volatility lose their "
                "trailing history."
            ),
            module="scripts.build_features",
            risk="heavy",
            timeout_seconds=6 * 3600,
            exclusive=True,
            params=(
                Param(
                    "days",
                    "Days of observations",
                    "int",
                    "--days",
                    help="Default 400, as the nightly uses.",
                    default=400,
                    minimum=7,
                    maximum=4000,
                ),
            ),
        ),
        TaskDef(
            key="score_rank",
            title="Score and rank",
            description="Recompute model.scores, rankings and predictions for the latest date.",
            module="scripts.score_rank",
            risk="write",
            timeout_seconds=3600,
            exclusive=True,
        ),
        TaskDef(
            key="populate_audit",
            title="Refresh audit tables",
            description="Rebuild audit.source_lineage and audit.data_quality from stored data.",
            module="scripts.populate_audit",
            risk="write",
            timeout_seconds=3600,
            exclusive=True,
        ),
        TaskDef(
            key="populate_market_data",
            title="Fetch market data",
            description=(
                "Fetch prices for the dividend universe, or for specific tickers. Calls the "
                "price provider; a full run takes over an hour."
            ),
            module="scripts.populate_market_data",
            risk="heavy",
            timeout_seconds=6 * 3600,
            exclusive=True,
            params=(
                Param(
                    "tickers",
                    "Tickers (comma separated)",
                    "tickers",
                    "--tickers",
                    help="Leave empty for the whole dividend universe.",
                ),
                Param(
                    "limit",
                    "Limit to the first N securities",
                    "int",
                    "--limit",
                    minimum=1,
                    maximum=20000,
                ),
            ),
        ),
        TaskDef(
            key="run_full_etl",
            title="Run the full ETL",
            description=(
                "The same pipeline as the nightly, started by hand. It takes its own pipeline "
                "lock and refuses to start if a run is already in flight. Runs for hours."
            ),
            module="scripts.run_full_etl",
            fixed_args=("--trigger", "manual"),
            risk="heavy",
            timeout_seconds=14 * 3600,
            params=(
                Param(
                    "limit",
                    "Limit to the first N securities",
                    "int",
                    "--limit",
                    help="For a trial run. Never combine with labels.",
                    minimum=1,
                    maximum=20000,
                ),
                Param(
                    "skip_derived",
                    "Skip derived stages",
                    "bool",
                    "--skip-derived",
                    help="Skip fundamentals, features, scoring and audit.",
                ),
            ),
        ),
    )
}


def get_task(key: str) -> TaskDef:
    try:
        return CATALOG[key]
    except (KeyError, TypeError):
        raise ValueError(f"unknown task {key!r}") from None


def _coerce(param: Param, value: Any) -> Any:
    """Return the canonical value for ``param`` or raise ValueError."""
    if param.kind == "bool":
        if isinstance(value, bool):
            return value
        raise ValueError(f"{param.name} must be true or false")
    if param.kind == "int":
        # bool is an int subclass; True would otherwise pass as 1.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{param.name} must be a whole number")
        if param.minimum is not None and value < param.minimum:
            raise ValueError(f"{param.name} must be at least {param.minimum}")
        if param.maximum is not None and value > param.maximum:
            raise ValueError(f"{param.name} must be at most {param.maximum}")
        return value
    if param.kind == "tickers":
        if not isinstance(value, str):
            raise ValueError(f"{param.name} must be text")
        # Validate the raw text, not a cleaned copy: cleaning first would quietly repair
        # "KO,," into "KO". Only spaces around the commas are tolerated.
        parts = [part.strip() for part in value.strip().split(",")]
        cleaned = ",".join(part.upper() for part in parts)
        if not _TICKERS.fullmatch(cleaned):
            raise ValueError(
                f"{param.name} must be 1-50 comma-separated tickers of letters, digits, '.' or '-'"
            )
        return cleaned
    if param.kind == "date":
        if isinstance(value, date):
            return value.isoformat()
        try:
            return date.fromisoformat(str(value)).isoformat()
        except ValueError:
            raise ValueError(f"{param.name} must be a YYYY-MM-DD date") from None
    raise ValueError(f"{param.name}: unsupported parameter kind {param.kind!r}")


def validate_params(key: str, raw: dict | None) -> dict:
    """Return the canonical parameters for ``key``; raises ValueError on any problem.

    Parameters the user left empty (None or an empty string) are dropped, so an optional
    field never turns into a flag with no value.
    """
    task = get_task(key)
    raw = {} if raw is None else raw
    if not isinstance(raw, dict):
        raise ValueError("parameters must be an object")
    known = {p.name: p for p in task.params}
    unknown = sorted(set(raw) - set(known))
    if unknown:
        raise ValueError(f"unknown parameter(s) for {key}: {', '.join(unknown)}")

    clean: dict[str, Any] = {}
    for name, param in known.items():
        value = raw.get(name, param.default)
        if value is None or value == "":
            continue
        value = _coerce(param, value)
        if param.kind == "bool" and value is False:
            continue
        clean[name] = value
    return clean


def build_argv(key: str, params: dict | None, *, python: str | None = None) -> list[str]:
    """The full command for a task, from the allowlist and validated parameters only."""
    task = get_task(key)
    clean = validate_params(key, params)
    argv = [python or sys.executable, "-m", task.module, *task.fixed_args]
    for param in task.params:
        if param.name not in clean:
            continue
        if param.kind == "bool":
            argv.append(param.flag)
        else:
            argv.extend([param.flag, str(clean[param.name])])
    return argv


def describe_command(key: str, params: dict | None) -> str:
    """A display string for the UI; the worker never runs it."""
    argv = build_argv(key, params, python="python")
    return " ".join(argv)
