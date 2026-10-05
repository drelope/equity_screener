from datetime import date

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://dividend:dividend@localhost:5432/dividend"
    sec_user_agent: str = "Your Name your.email@example.com"
    openbb_provider: str | None = None
    api_key: str | None = None
    min_recall: float = 0.30
    #: Horizon of the sustainability label. A feature row dated D is labelled
    #: from dividend events in (D, D + label_horizon_days], so this is also the
    #: minimum embargo between the training set and the test period.
    label_horizon_days: int = 365
    dividend_lookback_start: date = date(2025, 1, 1)
    #: Enforce the dividend-recency window when classifying the dividend
    #: universe. When False (the default) a security is flagged from any
    #: positive dividend fact, which is the historical behaviour and keeps the
    #: nightly ETL from silently changing the universe on an unattended run.
    #: Set ``ENFORCE_DIVIDEND_RECENCY=true`` to activate the bounded window.
    enforce_dividend_recency: bool = False
    #: How recent a positive dividend fact must be to count when
    #: ``enforce_dividend_recency`` is enabled. Matches the horizon the
    #: preferred dividend snapshot already uses.
    dividend_recency_days: int = 548
    #: Earliest price date. A 365-day label embargo leaves a training window
    #: of roughly 0.7 * span - 365 days, and momentum_252d/volatility_252d need
    #: 252 prior trading observations inside that window. With prices from
    #: 2023-09-01 the embargoed window held only 112 dates, so both 252-day
    #: features were structurally empty and the run could not be evaluated.
    #: 2019-01-01 leaves roughly five years of embargoed training history.
    price_lookback_start: date = date(2019, 1, 1)
    #: How far back a security's latest feature row may be and still be read on
    #: the current run. model.features holds one row per real observation date, so
    #: a security that did not trade on the run date has no row for it and used to
    #: drop out of the composite entirely: 155 active dividend payers had a print
    #: but no 2026-10-02 feature row, and this window makes 114 of them readable.
    #: It does not make them scoreable -- all 114 fall below MIN_PRESENT_WEIGHT --
    #: so expect this to widen the read window without moving any score. Set to 0
    #: for the strict common-date behaviour.
    feature_carry_forward_days: int = 7
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def require_sec_user_agent(self) -> None:
        ua = (self.sec_user_agent or "").strip()
        if not ua or "your.email" in ua.lower() or "@" not in ua:
            raise RuntimeError(
                "SEC_USER_AGENT must be a real contact string like "
                "'Name name@example.com' (SEC fair-access policy). Set it in .env "
                "before any SEC request."
            )


settings = Settings()
