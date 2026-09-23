from datetime import date

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://dividend:dividend@localhost:5432/dividend"
    sec_user_agent: str = "Your Name your.email@example.com"
    openbb_provider: str | None = None
    api_key: str | None = None
    min_recall: float = 0.30
    dividend_lookback_start: date = date(2025, 1, 1)
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
