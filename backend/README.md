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
| 缓存 | redis (redis-py asyncio) |
| 向量库 | Milvus (pymilvus) |
| 对象存储 | MinIO (minio-py) |
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
│   ├── cache/
│   │   └── redis.py            # redis.asyncio 连接池 + get_redis 依赖
│   ├── vectorstore/
│   │   └── milvus.py           # MilvusClient 单例 + ping 探活
│   ├── storage/
│   │   └── minio_client.py     # MinIO 单例 + ping 探活
│   ├── models/                 # ORM 模型（每张表一个类）
│   │   ├── user.py
│   │   ├── chat.py
│   │   ├── knowledge.py
│   │   └── memory.py
│   └── api/
│       └── health.py           # /health 端点（db/redis/milvus/minio 全探活）
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

### 4. 起中间件（首次）

```bash
cd ../docker
docker compose up -d         # postgres / redis / milvus(+etcd+minio)
```

> 本项目 docker-compose 实际部署在云服务器，本机通过 SSH 端口转发访问。
> 即使本机没有 Docker，只要端口（5432/6379/9000/9001/19530/9091）已转发到 localhost，
> 后端就能直接使用，无需改 host。

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

## 中间件：在代码里使用

### Redis（按请求依赖）

```python
from fastapi import APIRouter, Depends
from redis.asyncio import Redis

from app.cache.redis import get_redis

router = APIRouter()


@router.get("/counter")
async def incr(redis: Redis = Depends(get_redis)) -> dict:
    n = await redis.incr("visits")
    return {"visits": n}
```

要点：
- `get_redis` 从全局连接池借一个客户端句柄，请求结束后归还，**不需要业务代码 close**
- 默认 `decode_responses=True`，返回 str；存二进制（如 pickle/protobuf）需另开一个 pool
- 命令名与 redis-cli 一致：`get/set/incr/expire/hset/zadd/...`，全部 await

### Milvus（进程级单例）

```python
from app.vectorstore.milvus import get_milvus

client = get_milvus()
client.create_collection("docs", dimension=1536, metric_type="COSINE")
client.insert("docs", data=[{"id": 1, "vector": [...], "text": "..."}])
hits = client.search("docs", data=[query_vector], limit=5)
```

要点：
- `MilvusClient` 是同步 SDK，在异步路由里需要 `await asyncio.to_thread(client.search, ...)`
  包装，避免阻塞事件循环
- 集合（collection）≈ 关系库的表；schema 通过 dimension/metric_type 等参数声明
- 索引建议在数据导入后批量构建，而不是每次 insert

### MinIO（进程级单例）

```python
import io

from app.storage.minio_client import get_minio

minio = get_minio()
if not minio.bucket_exists("reports"):
    minio.make_bucket("reports")
minio.put_object("reports", "2026/05/r1.md", io.BytesIO(b"# hello"), length=7)
obj = minio.get_object("reports", "2026/05/r1.md")
content = obj.read()
```

要点：
- MinIO 走 S3 协议，对象 key 用 `/` 模拟目录层级
- minio-py 同样是同步 SDK，异步路由里同样用 `asyncio.to_thread` 包装
- bucket 命名遵循 S3 规则：小写字母、数字、连字符；初始化通常在业务启动逻辑里做

## 启动应用

```bash
# 开发模式（热重载）
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 验证：所有中间件通时 status=ok；任一不可达 status=degraded（HTTP 仍 200）
curl http://localhost:8000/health

# OpenAPI 文档
# http://localhost:8000/docs
```

`/health` 返回结构示例：

```json
{
  "status": "ok",
  "app": "industry-research-assistant",
  "env": "dev",
  "version": "0.1.0",
  "db":     {"status": "ok", "detail": null},
  "redis":  {"status": "ok", "detail": null},
  "milvus": {"status": "ok", "detail": "v2.4.17"},
  "minio":  {"status": "ok", "detail": "buckets=0"}
}
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

- 认证 / 用户模块（`/auth/register` `/auth/login` `/auth/me`）
- Repository 层抽象（替代裸 ORM 操作）
