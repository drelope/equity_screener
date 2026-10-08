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
    #: universe. On since 2026-10-06: a security is flagged only from a positive
    #: per-share dividend fact inside ``dividend_recency_days``, or a payment
    #: observed in that window (``dividend_universe``). The old any-fact-ever rule
    #: left 1,602 securities with a last fact 1.5 years old or older in the
    #: universe, and 1,413 more whose only recent tag was not a dividend they
    #: paid; the per-share rule (2026-10-07) drops aggregate payables and
    #: investor-side received-amount concepts entirely. Set
    #: ``ENFORCE_DIVIDEND_RECENCY=false`` to restore the any-fact-ever rule.
    enforce_dividend_recency: bool = True
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
    #: Token that unlocks operator actions in the web app (queueing, scheduling and
    #: cancelling tasks). Unset or shorter than 12 characters disables them: the app
    #: then shows data and monitoring read-only, never an unauthenticated control panel.
    ops_admin_token: str | None = None
    #: Where the web app reaches the data API, and the key it sends. The key is the API's
    #: own ``API_KEY``; the app never shows it.
    api_base_url: str = "http://localhost:8000"
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
