"""Redis 缓存客户端封装。"""

from app.cache.redis import dispose_redis, get_redis, get_redis_pool

__all__ = ["dispose_redis", "get_redis", "get_redis_pool"]
