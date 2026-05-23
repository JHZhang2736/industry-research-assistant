from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "industry-research-assistant"
    env: Literal["dev", "test", "prod"] = "dev"
    debug: bool = True
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)

    database_url: str = Field(
        default="postgresql+asyncpg://deepresearch:deepresearch@localhost:5432/deepresearch",
        description="SQLAlchemy async DSN，必须使用 postgresql+asyncpg 驱动。",
    )
    db_echo: bool = False
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=20, ge=0, le=200)


@lru_cache
def get_settings() -> Settings:
    return Settings()
