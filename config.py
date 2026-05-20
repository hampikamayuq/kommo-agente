from typing import Literal
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

    WEBHOOK_SECRET: str = ""
    API_KEY: str = ""

    PORT: int = 8000
    MAX_HISTORY_TURNS: int = 20
    DB_PATH: str = "conversations.db"

    HUMAN_TIMEOUT_HOURS: int = 4
    BOT_TIMEOUT_MINUTES: int = 30


settings = Settings()
