import pytest

from src.crispdm.ledger_opt_in import persist_run_if_opted_in


def base_manifest():
    return {
        "run_id": "r1",
        "run_type": "test",
        "created_at_utc": "2026-11-18T00:00:00+00:00",
    }


def test_disabled_returns_none():
    assert (
        persist_run_if_opted_in(
            manifest=base_manifest(),
            outputs=[],
            dsn=None,
            enabled=False,
            acknowledge=False,
            recorded_by="test",
        )
        is None
    )


def test_requires_dsn_and_acknowledgement():
    with pytest.raises(ValueError, match="ledger DSN"):
        persist_run_if_opted_in(
            manifest=base_manifest(),
            outputs=[],
            dsn=None,
            enabled=True,
            acknowledge=False,
            recorded_by="test",
        )
    with pytest.raises(ValueError, match="acknowledgement"):
        persist_run_if_opted_in(
            manifest=base_manifest(),
            outputs=[],
            dsn="postgresql://u:p@localhost:55499/rehearsal",
            enabled=True,
            acknowledge=False,
            recorded_by="test",
        )


def test_refuses_shared_like_database():
    with pytest.raises(ValueError, match="shared/production-like"):
        persist_run_if_opted_in(
            manifest=base_manifest(),
            outputs=[],
            dsn="postgresql://u:p@localhost:5432/dividend",
            enabled=True,
            acknowledge=True,
            recorded_by="test",
        )


def test_refuses_nonlocal_host():
    with pytest.raises(ValueError, match="non-local"):
        persist_run_if_opted_in(
            manifest=base_manifest(),
            outputs=[],
            dsn="postgresql://u:p@remotehost:5432/rehearsal",
            enabled=True,
            acknowledge=True,
            recorded_by="test",
        )
