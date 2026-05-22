from typing import Literal
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    KOMMO_SUBDOMAIN: str = ""
    KOMMO_API_TOKEN: str = ""

    AI_PROVIDER: Literal["openai", "anthropic"] = "openai"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_MODEL: str = "claude-sonnet-4-6"

    KOMMO_BOT_USER_ID: str = "11783975"
    # JSON dict mapping Kommo stage names (as the AI returns them) to their numeric status_id.
    # Example: KOMMO_STAGE_MAP={"Aguardando Horários": 12345678, "Consulta Confirmada": 23456789}
    KOMMO_STAGE_MAP: dict[str, int] = {}

    WEBHOOK_SECRET: str = ""
    API_KEY: str = ""

    PORT: int = 8000
    MAX_HISTORY_TURNS: int = 20
    DB_PATH: str = "conversations.db"

    HUMAN_TIMEOUT_HOURS: int = 4
    BOT_TIMEOUT_MINUTES: int = 3

    @model_validator(mode="after")
    def _require_secrets(self) -> "Settings":
        missing = [name for name, val in [("API_KEY", self.API_KEY), ("WEBHOOK_SECRET", self.WEBHOOK_SECRET)] if not val]
        if missing:
            raise ValueError(
                f"Missing required secrets: {', '.join(missing)}. "
                "Set them in your .env file or environment variables before starting the service."
            )
        return self


settings = Settings()
