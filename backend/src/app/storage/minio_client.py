"""MinIO 客户端封装。

使用官方 `minio` Python SDK（同步），通过 `asyncio.to_thread` 在异步路径中调度。
minio-py 是轻量、零额外依赖的 S3 协议客户端；如果将来需要走 S3 原生协议或
统一到 aioboto3，再换。

- 进程级单例，HTTP 连接复用由 urllib3 PoolManager 在 SDK 内部完成
- 探活走 `list_buckets()`，是 S3 协议里最轻的一次请求；返回值不关心，
  只要不抛异常就视为存活
"""

from __future__ import annotations

import asyncio
from functools import lru_cache

from minio import Minio

from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_minio() -> Minio:
    """构造进程级单例 MinIO 客户端。"""
    settings = get_settings()
    return Minio(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
        region=settings.minio_region,
    )


async def ping_minio() -> int:
    """探活：返回当前 bucket 数量。失败抛异常由调用方处理。"""
    client = get_minio()
    buckets = await asyncio.to_thread(client.list_buckets)
    return len(buckets)
