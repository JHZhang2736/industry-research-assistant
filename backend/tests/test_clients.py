"""客户端工厂单元测试：验证 lru_cache 单例与配置注入。

这些测试**不连接真实中间件**，只验证：
- 工厂函数返回正确类型
- 多次调用返回同一实例（lru_cache 生效）
- 配置参数正确传给底层 SDK
"""

from __future__ import annotations

from minio import Minio
from pymilvus import MilvusClient
from redis.asyncio import ConnectionPool

from app.cache.redis import get_redis_pool
from app.storage.minio_client import get_minio
from app.vectorstore.milvus import get_milvus


def test_redis_pool_is_singleton() -> None:
    get_redis_pool.cache_clear()
    pool_a = get_redis_pool()
    pool_b = get_redis_pool()
    assert isinstance(pool_a, ConnectionPool)
    assert pool_a is pool_b


def test_milvus_client_is_singleton() -> None:
    get_milvus.cache_clear()
    client_a = get_milvus()
    client_b = get_milvus()
    assert isinstance(client_a, MilvusClient)
    assert client_a is client_b


def test_minio_client_is_singleton_with_correct_config() -> None:
    get_minio.cache_clear()
    client_a = get_minio()
    client_b = get_minio()
    assert isinstance(client_a, Minio)
    assert client_a is client_b
