"""Milvus 客户端封装。

使用 pymilvus 2.5 提供的 `MilvusClient`（同步 SDK）。在 FastAPI 异步路径中
通过 `asyncio.to_thread` 调度阻塞调用。pymilvus 也提供了 `AsyncMilvusClient`，
但它目前仍在演进中且不少操作仍是同步包装；同步 + to_thread 是当前更稳的选择。

设计要点：
- 进程级单例（`lru_cache`），避免每请求重建 gRPC 连接
- 探活走 `get_server_version` 或 `list_databases`，都是轻量元数据调用
"""

from __future__ import annotations

import asyncio
from functools import lru_cache

from pymilvus import MilvusClient

from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_milvus() -> MilvusClient:
    """构造进程级单例 MilvusClient。

    `MilvusClient` 内部维护了 gRPC 连接通道；首次调用时建立连接，
    后续复用。token=None 时 pymilvus 会按"无鉴权"模式连接。
    """
    settings = get_settings()
    return MilvusClient(
        uri=settings.milvus_uri,
        token=settings.milvus_token or "",
        db_name=settings.milvus_db,
    )


async def ping_milvus() -> str:
    """探活：返回 server version 字符串。失败抛异常由调用方处理。"""
    client = get_milvus()
    return await asyncio.to_thread(client.get_server_version)


async def dispose_milvus() -> None:
    """应用关闭时释放 gRPC 通道。"""
    client = get_milvus()
    await asyncio.to_thread(client.close)
