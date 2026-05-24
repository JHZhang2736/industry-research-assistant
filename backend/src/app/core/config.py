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

    redis_url: str = Field(
        default="redis://:deepresearch@localhost:6379/0",
        description="Redis DSN，含密码。格式：redis://[:password]@host:port/db",
    )
    redis_max_connections: int = Field(default=50, ge=1, le=500)

    milvus_uri: str = Field(
        default="http://localhost:19530",
        description="Milvus 服务地址。pymilvus 2.5 推荐使用 URI 形式。",
    )
    milvus_token: str | None = Field(
        default=None,
        description="Milvus 鉴权 token（自建无鉴权可留空；Zilliz Cloud 必填）。",
    )
    milvus_db: str = Field(default="default", description="Milvus 数据库名（多租户隔离）。")

    minio_endpoint: str = Field(
        default="localhost:9000",
        description="MinIO 服务地址（host:port，不带 scheme）。",
    )
    minio_access_key: str = Field(default="minioadmin")
    minio_secret_key: str = Field(default="minioadmin")
    minio_secure: bool = Field(default=False, description="是否走 HTTPS。本地 dev 通常 false。")
    minio_region: str = Field(
        default="us-east-1", description="S3 协议要求字段，MinIO 任意值即可。"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
