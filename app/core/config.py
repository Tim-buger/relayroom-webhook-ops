from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    auto_create_schema: bool = False
    log_level: str = "INFO"
    database_url: str = "sqlite+aiosqlite:///./relayroom.db"
    redis_host: str = "localhost"
    redis_port: int = 6379
    webhook_signing_secret: str = "whsec_demo_secret"
    signature_tolerance_seconds: int = Field(default=300, ge=30, le=3600)
    max_payload_bytes: int = Field(default=262_144, ge=1024, le=10_485_760)
    destination_url: str = "http://127.0.0.1:8000/simulator/crm"
    delivery_timeout_seconds: float = Field(default=5, gt=0, le=30)
    max_delivery_attempts: int = Field(default=4, ge=1, le=10)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
