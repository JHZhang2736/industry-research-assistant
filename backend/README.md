# Backend — Industry Research Assistant

FastAPI 后端，多智能体编排引擎运行在此层。本文档说明本地开发环境与启动方式。

## 技术栈

| 项 | 选型 |
|----|------|
| Python | 3.12 |
| 包管理 | [uv](https://github.com/astral-sh/uv) |
| Web 框架 | FastAPI + Uvicorn |
| 配置 | pydantic-settings |
| 日志 | structlog |
| 测试 | pytest + httpx |
| Lint / Format / Type | ruff + mypy |

## 目录结构

```
backend/
├── pyproject.toml         # 依赖、ruff、mypy、pytest 配置
├── src/app/
│   ├── main.py            # FastAPI 实例与 lifespan
│   ├── core/
│   │   ├── config.py      # 配置（pydantic-settings）
│   │   └── logging.py     # structlog 配置
│   └── api/
│       └── health.py      # /health 端点
├── tests/
│   └── test_health.py
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

## 启动

```bash
# 开发模式（热重载）
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 验证
curl http://localhost:8000/health
# => {"status":"ok","app":"industry-research-assistant","env":"dev","version":"0.1.0"}

# OpenAPI 文档
# http://localhost:8000/docs
```

## 常用命令

```bash
uv run pytest                  # 跑测试
uv run ruff check .            # lint
uv run ruff format .           # 格式化
uv run mypy                    # 类型检查
```

## 当前进度

本 PR 只提供 **最小可启动骨架**。下一个 PR 接入：

- PostgreSQL / Redis / Milvus / MinIO 客户端封装
- `/health` 真实探活下游中间件
- Alembic migration 骨架
