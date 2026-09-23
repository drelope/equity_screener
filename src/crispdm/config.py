from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://dividend:dividend@localhost:5432/dividend"
    sec_user_agent: str = "Your Name your.email@example.com"
    openbb_provider: str | None = None
    api_key: str | None = None
    min_recall: float = 0.30
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
