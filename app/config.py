from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: str
    database_url: str = "sqlite+aiosqlite:///./data/safe_pilot.db"
    default_language: str = "en"
    useful_load_tolerance_lb: float = 5.0
    log_level: str = "INFO"


settings = Settings()
