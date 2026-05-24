"""pytest 全局 fixtures。

提供：
- `db_session`：每个测试一个 AsyncSession，绑定到真实 PG，测试结束**回滚**
  全部变更，相邻测试互不污染
- `client`：基于 httpx.AsyncClient + ASGITransport 的异步 HTTP 客户端，
  和 db_session 跑在**同一个** event loop 上，避免 asyncpg 跨 loop 报错

注意：测试依赖**真实**的本地 PG（通过 SSH 转发的云端容器也可），库需事先
`alembic upgrade head`。这是有意的：mock 数据库会漏掉唯一约束、外键、JSONB
等真实行为；本项目业务复杂度足以让这种漏检成为定时炸弹。

测试启动前把 bcrypt cost 调到 4，避免每条用例哈希 250ms。环境变量必须在
import app.* 之前生效。
"""

from __future__ import annotations

import os

# Must run before app.* imports so Settings sees the override.
os.environ.setdefault("BCRYPT_ROUNDS", "4")

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.db.session import get_db
from app.main import app


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """每个测试一个事务隔离的 session。

    实现：开 engine connection 后立即 begin transaction，session 绑到这条 connection；
    测试结束 rollback transaction，session 内所有写入消失。
    """
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    connection = await engine.connect()
    transaction = await connection.begin()
    session_factory = async_sessionmaker(
        bind=connection, class_=AsyncSession, expire_on_commit=False
    )
    session = session_factory()
    try:
        yield session
    finally:
        await session.close()
        if transaction.is_active:
            await transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """ASGI 异步客户端：覆盖 get_db 让路由用 fixture 的事务 session。"""

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_db, None)
