from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Keep configuration importable for migrations, static tooling, and tests that do not start
    # Telegram. The executable entry point validates the secret immediately before Bot creation.
    bot_token: str = ""
    database_url: str = "sqlite+aiosqlite:///./data/safe_pilot.db"
    default_language: str = "en"
    useful_load_tolerance_lb: float = 5.0
    log_level: str = "INFO"

    def required_bot_token(self) -> str:
        token = self.bot_token.strip()
        if not token:
            raise RuntimeError(
                "BOT_TOKEN is not configured. Copy .env.example to .env and set a new "
                "BotFather token before starting the Telegram bot."
            )
        return token


settings = Settings()
