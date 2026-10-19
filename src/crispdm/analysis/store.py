"""Investment-analysis worksheet storage (``analysis.investment_analyses``).

Every function takes an open SQLAlchemy connection and never commits, so the caller
owns the transaction: the app wraps calls in ``engine.begin()`` and the tests wrap them
in a transaction they roll back. Field-level validation lives in the worksheet itself
(``app/analysis_schema.py``); this module only enforces the payload's shape, because
the column CHECK constraints assume the app has already run that validation.
"""

from __future__ import annotations

import json

from sqlalchemy import text


def _rows(conn, sql: str, params: dict | None = None) -> list[dict]:
    return [dict(row) for row in conn.execute(text(sql), params or {}).mappings().all()]


def _dump(payload: dict) -> str:
    if not isinstance(payload, dict) or not payload.get("sections"):
        raise ValueError("the worksheet payload has no sections")
    return json.dumps(payload, sort_keys=True, default=str)


class StatusTransitionError(ValueError):
    """A Final worksheet may not silently return to being a Draft.

    Reopening a Final is a deliberate act (the recommendation was withdrawn or was
    premature); letting a stray save demote it would erase the distinction the saved-
    analyses list is built on.
    """

    def __init__(self, current: str, requested: str):
        super().__init__(
            f"a {current} worksheet can only become {requested} when the save is an "
            "explicit reopen"
        )
        self.current = current
        self.requested = requested


def create(
    conn,
    *,
    security_id: str,
    ticker: str,
    payload: dict,
    thesis: str,
    recommendation: str | None,
    confidence: str | None,
    overall_risk_score: int | None,
    status: str,
    created_by: str,
) -> int:
    """Insert a worksheet and return its id."""
    row = conn.execute(
        text("""
        INSERT INTO analysis.investment_analyses
            (security_id, ticker, status, schema_version, payload, thesis,
             recommendation, confidence, overall_risk_score, created_by)
        VALUES (CAST(:sid AS uuid), :ticker, :status, :version, CAST(:p AS jsonb),
                :thesis, :rec, :conf, :risk, :by)
        RETURNING analysis_id
    """),
        {
            "sid": security_id,
            "ticker": ticker,
            "status": status,
            "version": int(payload.get("version") or 1),
            "p": _dump(payload),
            "thesis": thesis,
            "rec": recommendation,
            "conf": confidence,
            "risk": overall_risk_score,
            "by": created_by,
        },
    ).scalar()
    return int(row)


def update(
    conn,
    analysis_id: int,
    *,
    payload: dict,
    thesis: str,
    recommendation: str | None,
    confidence: str | None,
    overall_risk_score: int | None,
    status: str,
    updated_by: str,
    reopen: bool = False,
) -> bool:
    """Overwrite a worksheet's content; True when the row existed.

    The row is locked for the rest of the caller's transaction while its current status
    is read, so a Final cannot be demoted to Draft between the check and the write.
    Pass ``reopen=True`` for a Final returning to Draft; anything else raises
    :class:`StatusTransitionError`.
    """
    locked = conn.execute(
        text("SELECT status FROM analysis.investment_analyses WHERE analysis_id = :id FOR UPDATE"),
        {"id": analysis_id},
    ).first()
    if locked is None:
        return False
    current_status = str(locked[0])
    if current_status == "final" and status == "draft" and not reopen:
        raise StatusTransitionError(current_status, status)
    row = conn.execute(
        text("""
        UPDATE analysis.investment_analyses
        SET payload = CAST(:p AS jsonb), schema_version = :version, thesis = :thesis,
            recommendation = :rec, confidence = :conf, overall_risk_score = :risk,
            status = :status, updated_by = :by, updated_at = now()
        WHERE analysis_id = :id
    """),
        {
            "id": analysis_id,
            "p": _dump(payload),
            "version": int(payload.get("version") or 1),
            "thesis": thesis,
            "rec": recommendation,
            "conf": confidence,
            "risk": overall_risk_score,
            "status": status,
            "by": updated_by,
        },
    ).rowcount
    return bool(row)


def list_for_security(conn, security_id: str) -> list[dict]:
    """Saved worksheets for one security, newest first."""
    return _rows(
        conn,
        """
        SELECT analysis_id, ticker, status, schema_version, thesis, recommendation,
               confidence, overall_risk_score, created_by, updated_by, created_at,
               updated_at
        FROM analysis.investment_analyses
        WHERE security_id = CAST(:sid AS uuid)
        ORDER BY created_at DESC, analysis_id DESC
        """,
        {"sid": security_id},
    )


def get(conn, analysis_id: int) -> dict | None:
    rows = _rows(
        conn,
        "SELECT * FROM analysis.investment_analyses WHERE analysis_id = :id",
        {"id": analysis_id},
    )
    return rows[0] if rows else None


def delete(conn, analysis_id: int) -> bool:
    return bool(
        conn.execute(
            text(
                "DELETE FROM analysis.investment_analyses WHERE analysis_id = :id "
                "RETURNING analysis_id"
            ),
            {"id": analysis_id},
        ).first()
    )


def revisions(conn, analysis_id: int) -> list[dict]:
    """Saved versions of one worksheet, newest first (see V0088).

    The first save and every later one land here, written by a trigger, so this is the
    worksheet's full history rather than only the current state.
    """
    return _rows(
        conn,
        """
        SELECT revision_id, status, schema_version, thesis, recommendation, confidence,
               overall_risk_score, saved_by, saved_at, payload
        FROM analysis.investment_analysis_revisions
        WHERE analysis_id = :id
        ORDER BY revision_id DESC
        """,
        {"id": analysis_id},
    )


def recommendation_history(conn, security_id: str) -> list[dict]:
    """Every change of recommended call for one security, newest first.

    A worksheet is usually re-saved many times with the same recommendation, so this
    keeps only the saves where the call differs from the previous one for that worksheet:
    the moments the analyst actually changed their mind. It is derived from the V0088
    revisions table, so it needs no extra storage and cannot drift from the saved calls.

    Recommendations withdrawn (the call set back to empty) are dropped along with every
    other NULL, because the track record is the sequence of calls that were made, not the
    gaps between them. ``previous`` is NULL for a worksheet's first recorded call.
    """
    return _rows(
        conn,
        """
        WITH calls AS (
            SELECT r.analysis_id, r.revision_id, r.saved_at, r.saved_by, r.status,
                   r.recommendation,
                   LAG(r.recommendation) OVER (
                       PARTITION BY r.analysis_id ORDER BY r.revision_id
                   ) AS previous
            FROM analysis.investment_analysis_revisions r
            JOIN analysis.investment_analyses a ON a.analysis_id = r.analysis_id
            WHERE a.security_id = CAST(:sid AS uuid)
              AND r.recommendation IS NOT NULL
        )
        SELECT analysis_id, revision_id, saved_at, saved_by, status, recommendation, previous
        FROM calls
        WHERE previous IS DISTINCT FROM recommendation
        ORDER BY revision_id DESC
        """,
        {"sid": security_id},
    )
