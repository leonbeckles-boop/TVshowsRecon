# app/services/core/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, AliasChoices


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # Example service config (update fields as needed)
    service_url: str = Field(
        "http://localhost:8000",
        validation_alias=AliasChoices("SERVICE_URL", "service_url"),
    )
    api_key: str | None = Field(
        None,
        validation_alias=AliasChoices("SERVICE_API_KEY", "service_api_key"),
    )
    

settings = Settings()
