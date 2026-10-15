"""Shared test configuration.

Most of the suite is pure and runs anywhere. A subset needs the live, migrated
Postgres warehouse, and each of those modules already declares its own readiness
probe (a module-level ``_live_engine`` or ``_database_ready`` that returns the
engine or ``None``). Two things happen here so that convention does one more job:

* The ``integration`` marker is registered, and every module that declares a
  probe is tagged with it. That gives a fast lane with no database:

      pytest -m "not integration"

  Keeping the tagging here rather than editing twenty modules means a new
  warehouse-backed module opts in just by defining ``_live_engine``.
* ``db_engine`` / ``db_conn`` fixtures are available for new DB tests, so a test
  no longer has to re-roll its own readiness probe and rollback scaffolding.
"""

from __future__ import annotations

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: needs the live, migrated Postgres warehouse",
    )


def pytest_collection_modifyitems(config, items):
    for item in items:
        try:
            module = item.module
        except Exception:  # noqa: S112 - module failed to import; leave it unmarked
            continue
        if hasattr(module, "_live_engine") or hasattr(module, "_database_ready"):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(scope="session")
def db_engine():
    """The live engine, or skip the test when the warehouse is unreachable."""
    try:
        from src.crispdm.db import engine

        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception:  # pragma: no cover - depends on the environment
        pytest.skip("no live database")
    return engine


@pytest.fixture
def db_conn(db_engine):
    """A connection inside a transaction that is always rolled back."""
    with db_engine.connect() as conn:
        outer = conn.begin()
        try:
            yield conn
        finally:
            outer.rollback()
