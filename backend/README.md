# Backend — Industry Research Assistant

FastAPI 后端，多智能体编排引擎运行在此层。本文档说明本地开发环境、启动方式与数据库操作指南。

## 技术栈

| 项 | 选型 |
|----|------|
| Python | 3.12 |
| 包管理 | [uv](https://github.com/astral-sh/uv) |
| Web 框架 | FastAPI + Uvicorn |
| 配置 | pydantic-settings |
| 日志 | structlog |
| ORM | SQLAlchemy 2.x (async) + asyncpg |
| 迁移 | Alembic |
| 测试 | pytest + httpx |
| Lint / Format / Type | ruff + mypy |

## 目录结构

```
backend/
├── pyproject.toml              # 依赖、ruff、mypy、pytest 配置
├── alembic.ini                 # Alembic 配置
├── alembic/
│   ├── env.py                  # 异步迁移环境（从 app.core.config 注入 DSN）
│   ├── script.py.mako          # 迁移文件模板
│   └── versions/               # 迁移版本文件
├── src/app/
│   ├── main.py                 # FastAPI 实例与 lifespan
│   ├── core/
│   │   ├── config.py           # 配置（pydantic-settings）
│   │   └── logging.py          # structlog 配置
│   ├── db/
│   │   ├── base.py             # DeclarativeBase
│   │   └── session.py          # async engine + sessionmaker + get_db 依赖
│   ├── models/                 # ORM 模型（每张表一个类）
│   │   ├── user.py
│   │   ├── chat.py
│   │   ├── knowledge.py
│   │   └── memory.py
│   └── api/
│       └── health.py           # /health 端点（带 db 探活）
├── tests/
├── .env.example
└── README.md
```

## 准备环境

### 1. 安装 uv

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2. 安装依赖

```bash
cd backend
uv sync              # 创建 .venv 并安装运行时 + dev 依赖
```

### 3. 复制环境变量

```bash
cp .env.example .env
```

### 4. 起 PostgreSQL（首次）

```bash
cd ../docker
docker compose up -d postgres
```

## 数据库：升级与日常操作

### 一、初始化（首次拉代码或库为空时）

```bash
cd backend
uv run alembic upgrade head
```

执行后 PG 中会出现 6 张业务表（`users` / `chat_sessions` / `chat_messages` /
`knowledge_bases` / `documents` / `long_term_memories`），以及触发器
`update_updated_at_column` 与 `alembic_version` 版本记录表。

### 二、查看当前迁移状态

```bash
uv run alembic current              # 当前数据库 head
uv run alembic history --verbose    # 全部迁移版本
uv run alembic heads                # 代码侧的 head（与 current 对齐才算同步）
```

### 三、新增 / 修改 schema 的标准流程

1. **改 ORM 模型**：在 `src/app/models/` 下新增字段、新建模型类或修改约束
2. **自动生成迁移**：

   ```bash
   uv run alembic revision --autogenerate -m "<简短中文描述>"
   ```

   Alembic 会 diff "ORM metadata" 与 "当前数据库 schema"，把差异写入
   `alembic/versions/<timestamp>_xxx.py`
3. **审阅生成结果**：autogenerate 不是万能（无法识别列重命名、约束类型变化），
   打开文件检查 `upgrade()` / `downgrade()` 是否符合预期，必要时手改
4. **应用到数据库**：

   ```bash
   uv run alembic upgrade head
   ```

5. **提交**：迁移文件**必须随业务代码一起进 git**

### 四、回滚

```bash
uv run alembic downgrade -1            # 回滚一步
uv run alembic downgrade <revision>    # 回滚到指定版本
uv run alembic downgrade base          # 清空到无迁移状态（慎用，会丢业务数据）
```

### 五、生成 SQL 而不执行（用于线上审阅）

```bash
uv run alembic upgrade head --sql > upgrade.sql
```

## 在代码里操作数据库

### 路由层：通过依赖注入拿 session

```python
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User

router = APIRouter()


@router.get("/users")
async def list_users(db: AsyncSession = Depends(get_db)) -> list[dict]:
    stmt = select(User).order_by(User.created_at.desc()).limit(20)
    result = await db.execute(stmt)
    users = result.scalars().all()
    return [{"id": str(u.id), "email": u.email} for u in users]


@router.post("/users")
async def create_user(email: str, db: AsyncSession = Depends(get_db)) -> dict:
    user = User(username=email.split("@")[0], email=email, hashed_password="...")
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return {"id": str(user.id)}
```

要点：
- `get_db` 是按请求创建一个 `AsyncSession`，请求结束自动关闭
- **写操作要显式 `await db.commit()`**，否则不会落盘
- `await db.refresh(obj)` 把数据库填回的字段（PK、`server_default`）刷到对象上

### 非路由场景（脚本、后台任务）：手动开 session

```python
from app.db.session import async_session_factory

async def some_job() -> None:
    session_factory = async_session_factory()
    async with session_factory() as db:
        async with db.begin():
            ...  # 事务里做事，退出 with 自动 commit；抛异常自动 rollback
```

### 常见查询模式

```python
# 按主键拿
user = await db.get(User, user_id)

# 条件查询
stmt = select(User).where(User.email == "x@y.com")
user = (await db.execute(stmt)).scalar_one_or_none()

# 分页 + 排序
stmt = select(ChatSession).where(ChatSession.user_id == uid)\
    .order_by(ChatSession.created_at.desc()).limit(20).offset(40)
sessions = (await db.execute(stmt)).scalars().all()

# 更新
user.is_active = False
await db.commit()

# 删除
await db.delete(user)
await db.commit()
```

## 启动应用

```bash
# 开发模式（热重载）
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 验证：DB 通时 status=ok，断 DB 时 status=degraded（HTTP 仍 200）
curl http://localhost:8000/health

# OpenAPI 文档
# http://localhost:8000/docs
```

## 常用命令

```bash
uv run pytest                  # 跑测试
uv run ruff check .            # lint
uv run ruff format .           # 格式化
uv run mypy                    # 类型检查
uv run alembic upgrade head    # 升级到最新 schema
```

## 下一个 PR 计划

- Redis / Milvus / MinIO 客户端封装
- `/health` 增加 redis / milvus / minio 探活字段
