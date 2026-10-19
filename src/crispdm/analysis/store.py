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
) -> bool:
    """Overwrite a worksheet's content; True when the row existed."""
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
