"""验证 db 模块导出与 engine 工厂的形态。

不连接真实数据库；连接性验证由 /health 集成测试和手工 `alembic upgrade head` 覆盖。
"""

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db import Base, async_session_factory, get_engine


def test_base_metadata_collects_all_models() -> None:
    """import models 模块后，Base.metadata 应包含全部 6 张业务表。"""
    import app.models  # noqa: F401

    table_names = set(Base.metadata.tables.keys())
    expected = {
        "users",
        "chat_sessions",
        "chat_messages",
        "knowledge_bases",
        "documents",
        "long_term_memories",
    }
    assert expected.issubset(table_names), f"missing tables: {expected - table_names}"


def test_get_engine_returns_async_engine() -> None:
    engine = get_engine()
    assert isinstance(engine, AsyncEngine)
    # 二次调用走 lru_cache，应返回同一实例
    assert get_engine() is engine


def test_async_session_factory_bound_to_engine() -> None:
    factory = async_session_factory()
    assert isinstance(factory, async_sessionmaker)
    assert factory.kw["bind"] is get_engine()
