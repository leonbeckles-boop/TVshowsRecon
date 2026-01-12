# app/core/settings.py
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # --- DB / cache ---
    database_url: Optional[str] = Field(default=None, alias="DATABASE_URL")  # e.g. postgresql+asyncpg://...
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # --- TMDb ---
    tmdb_api_key: Optional[str] = Field(default=None, alias="TMDB_API_KEY")
    tmdb_bearer_token: Optional[str] = Field(default=None, alias="TMDB_BEARER_TOKEN")

    # --- Reddit ---
    reddit_client_id: Optional[str] = Field(default=None, alias="REDDIT_CLIENT_ID")
    reddit_client_secret: Optional[str] = Field(default=None, alias="REDDIT_CLIENT_SECRET")
    # Optional convenience if you previously used REDDIT_SECRET
    reddit_secret: Optional[str] = Field(default=None, alias="REDDIT_SECRET")
    reddit_user_agent: Optional[str] = Field(default=None, alias="REDDIT_USER_AGENT")

    # Pydantic v2 settings config (replaces inner class Config)
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
    )

settings = Settings()
