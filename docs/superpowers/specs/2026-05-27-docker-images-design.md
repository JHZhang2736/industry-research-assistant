# Docker 镜像构建 + 推送设计

> 日期：2026-05-27
> 类型：CI/CD 基础设施 — 子项目 B（共 3 个：A. CI 护栏 ✅ / B. Docker 镜像 / C. 自动部署）
> 状态：设计稿，待实施

---

## 1. 背景与动机

子项目 A（PR 质量护栏）已落地。子项目 B 的目标：把后端 + 前端打成 Docker 镜像 push 到 registry，为子项目 C（自动部署）打基础。

**当前 Docker 设施现状（半成品 + 不一致）：**

| 项 | 状态 |
|---|---|
| `backend/app/Dockerfile` | ✅ 存在 但有问题（用清华源、单 stage、build context 错位） |
| `backend/docker-compose-base.yml` | ⚠️ 只有 Redis + Milvus 三件套，**没有 Postgres**（项目主 DB） |
| `backend/requirements.txt` + `backend/app/requirements.txt` | ❌ **两份内容不同**：外层用 `>=` 完整、含 langgraph/pymilvus；内层用 `==` 精确但缺核心依赖 |
| Dockerfile 用的 requirements | 内层（缺 langgraph 等关键库）→ 实际从未跑通过 |
| `frontend/Dockerfile` | ❌ 不存在 |
| frontend / backend / postgres 在 compose | ❌ 都不在 |
| `.dockerignore` | ❌ 两端都没（build context 会带 node_modules / __pycache__ 等） |
| CI 镜像 build + push 流水线 | ❌ 不存在 |

---

## 2. 范围

### 做

- **整理 requirements**：删 `backend/app/requirements.txt`，外层 `backend/requirements.txt` 为唯一 source；先 grep 内层独有依赖（gunicorn / fastapi-jwt / xgboost / beartype / dotenv / dashscope / llama-index-postprocessor-dashscope-rerank-custom）的实际用法，用到的合并进外层，没用到的舍弃
- **删 `backend/app/Dockerfile`**（半成品），改写到 `backend/Dockerfile`
- **新增 `backend/Dockerfile`**（多阶段，build context = `backend/`）
- **新增 `backend/.dockerignore`**
- **新增 `frontend/Dockerfile`**（多阶段 node-build → nginx-serve）
- **新增 `frontend/.dockerignore`**
- **新增 `frontend/nginx.conf`**（SPA fallback + `/api/*` proxy 到 backend）
- **新增根 `docker-compose.yml`**（完整应用栈：postgres + redis + milvus + backend + frontend）
- **新增 `.github/workflows/docker.yml`**（push to main 触发，并行 build + push backend/frontend 镜像到 GHCR）
- 本地 smoke：`docker compose up -d` 后 curl `/hello` 验证

### 不做（YAGNI / 后续子项目）

- ❌ 自动部署到服务器 → 子项目 C
- ❌ multi-arch（arm64）build → 当前部署目标默认 amd64
- ❌ 镜像签名（cosign） / 漏洞扫描（trivy） → 工具链未成熟前先简化
- ❌ docker compose up smoke 加进 CI → Milvus 启动 3+ min 太重，子项目 C 部署 staging 后 verify
- ❌ semver tag 推送（push tag 时自动 build） → 还没用 git tag 的习惯，先 latest + sha
- ❌ 改动 `backend/docker-compose-base.yml` → 保留作为"只起基础设施"的便捷文件供本地 dev 用

---

## 3. 设计决策

### 3.1 Requirements 单 source of truth

`backend/app/requirements.txt` 缺核心依赖（langgraph / pymilvus / langsmith / nltk / jieba / openai 等），说明它**从未真在生产用过**，是历史遗留。外层 `backend/requirements.txt` 是 CI 实际用的，活跃维护的。

决策：删内层，外层为唯一 source。Pre-flight 任务先 grep 内层独有的 5-7 个包的实际代码使用情况：

| 内层独有 | grep 验证 | 操作 |
|---|---|---|
| `gunicorn==21.0.0` | 实际生产入口用什么 | 若用则加入外层；不用则丢 |
| `fastapi-jwt[authlib]==0.3.0` | 是否有 `from fastapi_jwt import ...` | 同上（外层用 python-jose+passlib，可能冗余） |
| `xgboost` | 是否 `import xgboost` | 同上 |
| `beartype` | 是否 `from beartype` | 同上 |
| `dotenv==0.9.9` | 外层已有 `python-dotenv>=1.0.0` | 重复，丢内层 |
| `dashscope` | 是否 `import dashscope` | 同上（项目主要走 openai SDK 兼容模式） |
| `llama-index-postprocessor-dashscope-rerank-custom` | 外层有 `llama-index-postprocessor-dashscope-rerank`（无 -custom） | grep 用法决定保哪个 |

### 3.2 Dockerfile 移到 `backend/` 层级

原 `backend/app/Dockerfile` 的 build context = `backend/app/`，要求 requirements.txt 也在 `backend/app/`。决策把 Dockerfile 挪到 `backend/Dockerfile`，build context = `backend/`，COPY 步骤分两步：先 COPY requirements.txt 装依赖（leverages Docker layer cache），再 COPY app/ 装代码。

### 3.3 多阶段 build（backend + frontend 都用）

**Backend** 双阶段：
- builder：`python:3.11-slim` 跑 `pip install --user`
- runtime：`python:3.11-slim` 只 COPY 装好的 site-packages 和代码

收益：runtime 镜像不含 pip / build deps，~800 MB → ~500 MB。

**Frontend** 双阶段：
- builder：`node:20-alpine` 跑 `npm ci + npm run build`
- runtime：`nginx:alpine` 只 COPY dist + nginx config

收益：runtime ~50 MB（vs 包含 node_modules 的 ~800 MB）。

### 3.4 删清华 pip 源

CI runner 在 GitHub 海外，访问清华 mirror 可能不稳。直接用 pypi 默认。如果本地 build 慢，开发者自己加 `--index-url` 临时参数。

### 3.5 nginx 配置 `/api/*` proxy 到 backend

前端镜像跑 nginx serve static files；axios 调 `/api/...` 时 nginx 透传到同 compose 网络的 `backend:8000`。这样：
- dev：本地 docker compose up，访问 localhost:80 即可，axios 不需要知道 backend URL
- prod：同一 compose 部署，nginx 同样代理

### 3.6 Compose 文件双轨

- **`backend/docker-compose-base.yml`** 保留 → 本地开发"只起基础设施"用，方便本地 IDE 跑 backend 代码连这些服务
- **根 `docker-compose.yml`** 新增 → 完整应用栈（添加 postgres、backend、frontend），用于：
  - 本地完整 smoke
  - 后续子项目 C 部署到服务器

补充 Postgres：`postgres:16-alpine` + 默认 `industry_assistant` 数据库 + `postgres-data` named volume。

### 3.7 Registry: GHCR

GitHub Container Registry。优势：
- 零配置：workflow 直接用 `GITHUB_TOKEN` 登录 push
- Public package 免费且无 pull 限额
- 跟 GitHub repo 权限模型集成

镜像命名：
- `ghcr.io/jhzhang2736/industry-research-assistant-backend:latest`
- `ghcr.io/jhzhang2736/industry-research-assistant-backend:sha-<7char>`
- 同样 frontend

### 3.8 Tag 策略：`latest` + `sha-<7>`

- `latest`：默认 pull 取最新 main 构建
- `sha-<7>`：可 pin 到具体 commit，方便回滚

用 `docker/metadata-action@v5` 自动生成。

### 3.9 Buildkit registry cache

`docker/build-push-action@v5` 配置 `cache-from` / `cache-to` 指向 registry 上的 cache image（如 `ghcr.io/jhzhang2736/...-backend:buildcache`）。Cache hit 时 `pip install` 这一层直接复用，省 ~1.5 min。

### 3.10 触发：push to main only

不在 PR 上 build 镜像。理由：
- PR 上已有 CI 护栏 (tsc/eslint/build/pytest)，足够 catch 大多数构建问题
- Docker build 慢且占 storage（每个 PR 一份 cache layer 太废）
- 镜像 push 到 GHCR 后即代表"main 上的可部署版本"，PR 阶段不需要"可部署"

---

## 4. 性能预估

| 阶段 | Cache hit | Cache miss |
|---|---|---|
| backend Dockerfile build | ~2 min | ~4 min |
| frontend Dockerfile build | ~1.5 min | ~3 min |
| push to GHCR | ~30s | ~30s |
| **总 wall（并行）** | **~2.5 min** | **~4.5 min** |

---

## 5. 风险与回滚

| 风险 | 对策 |
|---|---|
| 删 `backend/app/requirements.txt` 后某个内层独有依赖被代码隐式 import 但 grep 没发现 | Pre-flight 任务 + 本地 docker compose up smoke 必跑（启动崩了说明缺包） |
| 新 backend Dockerfile 跟原 Dockerfile 行为不一致 | 保留原 `backend/app/Dockerfile` 文件到 commit 末才删；中间状态可对比 |
| GHCR 权限问题导致 push 失败 | 第一次 workflow run 在 repo settings → Actions permissions → Workflow permissions 改为 "Read and write" |
| nginx /api proxy 配错导致前端调用 404 | smoke 测试必须包含访问前端首页 → 触发 API call → 看 backend 收到 |
| docker compose up 在 Windows 启动 Milvus 慢 | 接受现状（用户已经在用，不在本子项目 scope） |

**回滚**：删 docker.yml + 改 docker-compose.yml + 删新 Dockerfile + 恢复原 `backend/app/Dockerfile` 和 `backend/app/requirements.txt`（git revert 整 commit）。

---

## 6. 后续（不在本 spec 范围）

- **子项目 C**：从 GHCR 拉镜像部署到服务器（云主机 SSH / 容器服务 / k8s）—— 需要先明确部署目标
- semver tag 推送 + release 自动化
- multi-arch（arm64 for Mac M-series / ARM 服务器）
- 镜像签名 + 漏洞扫描
- compose smoke test 进 CI
