"""健康检查端点。

聚合四类下游依赖的探活结果：PostgreSQL / Redis / Milvus / MinIO。
任一组件不可达时整体状态为 `degraded`，但 HTTP 仍返回 200 —— 由调用方
（负载均衡 / K8s liveness）按业务语义决定是否摘流。
"""

from __future__ import annotations

from typing import Literal

import structlog
from fastapi import APIRouter
from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.cache.redis import get_redis_pool
from app.core.config import get_settings
from app.db.session import get_engine
from app.storage.minio_client import ping_minio
from app.vectorstore.milvus import ping_milvus

router = APIRouter(tags=["health"])
log = structlog.get_logger(__name__)


class DependencyStatus(BaseModel):
    status: Literal["ok", "down"]
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    app: str
    env: str
    version: str
    db: DependencyStatus
    redis: DependencyStatus
    milvus: DependencyStatus
    minio: DependencyStatus


async def _probe_db() -> DependencyStatus:
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return DependencyStatus(status="ok")
    except SQLAlchemyError as exc:
        log.warning("db_health_probe_failed", error=str(exc))
        return DependencyStatus(status="down", detail=exc.__class__.__name__)


async def _probe_redis() -> DependencyStatus:
    pool = get_redis_pool()
    client: Redis = Redis(connection_pool=pool)
    try:
        # redis-py 的 Redis.ping() 在 asyncio 模式下返回 Awaitable[bool]，
        # 但其 type stub 同时声明了同步重载，mypy 推断为联合类型，这里显式 await。
        await client.ping()  # type: ignore[misc]
        return DependencyStatus(status="ok")
    except RedisError as exc:
        log.warning("redis_health_probe_failed", error=str(exc))
        return DependencyStatus(status="down", detail=exc.__class__.__name__)
    finally:
        await client.close()


async def _probe_milvus() -> DependencyStatus:
    try:
        version = await ping_milvus()
        return DependencyStatus(status="ok", detail=version)
    except Exception as exc:  # pymilvus 抛 MilvusException / 网络异常等，归一处理
        log.warning("milvus_health_probe_failed", error=str(exc))
        return DependencyStatus(status="down", detail=exc.__class__.__name__)


async def _probe_minio() -> DependencyStatus:
    try:
        bucket_count = await ping_minio()
        return DependencyStatus(status="ok", detail=f"buckets={bucket_count}")
    except Exception as exc:  # minio-py 抛 S3Error / urllib3 异常等，归一处理
        log.warning("minio_health_probe_failed", error=str(exc))
        return DependencyStatus(status="down", detail=exc.__class__.__name__)


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    db_status = await _probe_db()
    redis_status = await _probe_redis()
    milvus_status = await _probe_milvus()
    minio_status = await _probe_minio()

    deps = (db_status, redis_status, milvus_status, minio_status)
    overall: Literal["ok", "degraded"] = "ok" if all(d.status == "ok" for d in deps) else "degraded"

    return HealthResponse(
        status=overall,
        app=settings.app_name,
        env=settings.env,
        version=__version__,
        db=db_status,
        redis=redis_status,
        milvus=milvus_status,
        minio=minio_status,
    )
