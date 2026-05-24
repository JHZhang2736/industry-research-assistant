"""异步 Redis 客户端工厂。

使用 redis.asyncio 提供的连接池模式：
- `get_redis_pool()` 进程内单例连接池，应用启停期间复用
- `get_redis()` FastAPI 依赖，按请求返回从池中借出的 Redis 句柄

注意：Redis 客户端从连接池借连接是无成本的（不会真的握手），
所以无需在依赖里 `try/finally close`，连接对象本身就是池的代理。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from redis.asyncio import ConnectionPool, Redis

from app.core.config import get_settings


@lru_cache(maxsize=1)
def get_redis_pool() -> ConnectionPool:
    """构造进程级单例连接池。

    `decode_responses=True` 让命令返回 str 而不是 bytes，
    业务侧绝大多数场景需要的是 str；如果将来要塞二进制（如 pickle 缓存），
    再针对那个场景单独建一个 decode_responses=False 的池。
    """
    settings = get_settings()
    return ConnectionPool.from_url(
        settings.redis_url,
        max_connections=settings.redis_max_connections,
        decode_responses=True,
    )


async def get_redis() -> AsyncIterator[Redis]:
    """FastAPI 依赖：返回绑定到全局池的 Redis 句柄。"""
    pool = get_redis_pool()
    client: Redis = Redis(connection_pool=pool)
    try:
        yield client
    finally:
        await client.close()


async def dispose_redis() -> None:
    """应用关闭时释放连接池。"""
    pool = get_redis_pool()
    await pool.disconnect(inuse_connections=True)
