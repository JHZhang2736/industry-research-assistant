from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
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

    cors_origins: list[str] = Field(
        default=[
            "http://localhost:5183",
            "http://127.0.0.1:5183",
        ],
        description="允许跨域请求的 Origin 白名单。env 中用逗号分隔多个值。",
    )
    cors_allow_credentials: bool = Field(
        default=True,
        description="是否允许携带 cookie/Authorization。生产建议明确白名单后保持 True。",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, v: object) -> object:
        """允许 env 用逗号分隔传入，提升可读性（默认 pydantic 期待 JSON）。"""
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

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

    jwt_secret_key: str = Field(
        default="CHANGE_ME_TO_RANDOM_64_BYTES_USE_openssl_rand_hex_32",
        description="JWT 签名密钥。生产环境必须替换为高熵随机串（如 `openssl rand -hex 32`）。",
        min_length=32,
    )
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_access_ttl_minutes: int = Field(
        default=60 * 24 * 7,
        ge=1,
        le=60 * 24 * 30,
        description="Access token 有效期（分钟）。默认 7 天。",
    )
    bcrypt_rounds: int = Field(
        default=12,
        ge=4,
        le=15,
        description="bcrypt cost factor。默认 12（≈250ms/次）。测试环境可调低到 4 加速。",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
