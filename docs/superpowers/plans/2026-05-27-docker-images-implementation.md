# Docker 镜像构建 + 推送 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 backend + frontend 打成 Docker 镜像 push 到 GitHub Container Registry (GHCR)，并整理本地 docker-compose 完整应用栈，为子项目 C（自动部署）打基础。

**Architecture:** 两个多阶段 Dockerfile（`backend/Dockerfile` 用 python:3.11-slim 双 stage；`frontend/Dockerfile` 用 node:20-alpine → nginx:alpine 双 stage）。根 `docker-compose.yml` 串起 postgres + redis + milvus + backend + frontend。新 workflow `docker.yml` 在 push to main 时并行 build + push 两个镜像到 GHCR，tag = `latest` + `sha-<7>`。

**Tech Stack:** Docker multi-stage build, BuildKit, docker/build-push-action@v5, docker/metadata-action@v5, GitHub Container Registry (ghcr.io), nginx:alpine, postgres:16-alpine, Python 3.11, Node 20

**Spec Reference:** `docs/superpowers/specs/2026-05-27-docker-images-design.md`

---

## File Structure

| 文件 | 操作 | 责任 |
|---|---|---|
| `backend/app/Dockerfile` | **删** | 半成品，废弃 |
| `backend/app/requirements.txt` | **删** | 内容残缺（缺 langgraph/pymilvus 等），废弃，外层为唯一 source |
| `backend/requirements.txt` | **改** | 把内层独有且实际用到的包合并进来 |
| `backend/Dockerfile` | **新建** | 多阶段，build context = `backend/` |
| `backend/.dockerignore` | **新建** | 排除 __pycache__ / .env / .eval.db / app/eval 等 |
| `backend/docker-compose-base.yml` | **保留不动** | 本地开发"只起基础设施"用 |
| `frontend/Dockerfile` | **新建** | 多阶段 node-build → nginx-serve |
| `frontend/.dockerignore` | **新建** | 排除 node_modules / dist 等 |
| `frontend/nginx.conf` | **新建** | SPA fallback + `/api/*` proxy 到 backend:8000 |
| `docker-compose.yml` | **新建** | 根目录，完整应用栈 = postgres + redis + milvus + backend + frontend |
| `.github/workflows/docker.yml` | **新建** | push to main 触发 build + push 镜像到 GHCR |

---

## 执行顺序

```
Task 1  Requirements 整理（grep + 合并 + 删内层）
Task 2  Backend Dockerfile + .dockerignore
Task 3  Frontend nginx.conf + Dockerfile + .dockerignore
Task 4  根 docker-compose.yml
Task 5  本地 smoke (docker compose up 启全栈，curl /hello 验证)
Task 6  GitHub Actions workflow (.github/workflows/docker.yml)
Task 7  Commit + push + 开 PR + 验证 Actions push GHCR 成功
Task 8  本地 pull GHCR 镜像 verify 跑得起来
```

---

## Task 1: Requirements 整理

**Files:**
- Modify: `backend/requirements.txt`
- Delete: `backend/app/requirements.txt`
- Delete: `backend/app/Dockerfile`（在 Task 2 之前清场，避免歧义）

- [ ] **Step 1: grep 内层独有依赖的实际用法**

```bash
cd "D:/桌面/大模型/agent实战/第六周/industry-research-assistant"
echo "=== gunicorn ==="; grep -rE "gunicorn" backend/app/ --include="*.py" 2>&1 | head -3
echo "=== fastapi-jwt ==="; grep -rE "fastapi_jwt|from fastapi_jwt" backend/app/ --include="*.py" 2>&1 | head -3
echo "=== xgboost ==="; grep -rE "import xgboost|from xgboost" backend/app/ --include="*.py" 2>&1 | head -3
echo "=== beartype ==="; grep -rE "import beartype|from beartype" backend/app/ --include="*.py" 2>&1 | head -3
echo "=== dashscope ==="; grep -rE "import dashscope|from dashscope" backend/app/ --include="*.py" 2>&1 | head -3
echo "=== rerank-custom ==="; grep -rE "dashscope_rerank|llama_index.postprocessor.dashscope" backend/app/ --include="*.py" 2>&1 | head -3
```

每行第一个空说明该包**未被引用**，可以丢；有匹配则需要合并进外层。

- [ ] **Step 2: 根据 grep 结果更新 `backend/requirements.txt`**

把 grep 命中的内层独有包加到外层对应分组下（pin 到内层的版本号）。可能的合并样例：

```diff
  # Web Framework
  fastapi>=0.104.0
  uvicorn[standard]>=0.24.0
+ gunicorn>=21.0.0       # 如果 grep 命中
  python-multipart>=0.0.6
  python-dotenv>=1.0.0
```

如果 `fastapi-jwt` 命中，把它放到 Authentication 分组：

```diff
  # Authentication
- python-jose[cryptography]>=3.3.0
- passlib[bcrypt]>=1.7.4
+ fastapi-jwt[authlib]>=0.3.0
  pydantic[email]>=2.5.0
```

> 实际编辑根据 grep 结果做。Step 1 输出是这步的输入。

- [ ] **Step 3: 删内层 requirements 和 Dockerfile**

```bash
git rm backend/app/requirements.txt backend/app/Dockerfile
```

- [ ] **Step 4: 验证外层 requirements 可装**

```bash
cd "D:/桌面/大模型/agent实战/第六周/industry-research-assistant/backend"
pip install --dry-run -r requirements.txt 2>&1 | tail -10
```

Expected：无 "Could not find a version" 类报错。

> 如果遇到本地 pip 跟 PyPI 通讯问题，这步可跳过 —— Task 5 的 docker build 会强制验证。

- [ ] **Step 5: 暂存（不 commit，留到 Task 7 一并）**

```bash
git status --short backend/
```

Expected：
```
M  backend/requirements.txt
D  backend/app/requirements.txt
D  backend/app/Dockerfile
```

---

## Task 2: Backend Dockerfile + .dockerignore

**Files:**
- Create: `backend/Dockerfile`
- Create: `backend/.dockerignore`

- [ ] **Step 1: 创建 `backend/.dockerignore`**

```
# Python
__pycache__/
*.py[cod]
*.so
*.egg-info/
.pytest_cache/

# Local dev / secrets
.env
.env.*
!.env.example

# Eval framework local files
app/eval/.eval.db
app/eval/.eval.db-*

# Backup / git artifacts
backup/
.git/
.gitignore

# Editor / OS
.vscode/
.idea/
.DS_Store
Thumbs.db

# Logs
*.log
/tmp/

# Docs (不需要打进 image)
docs/

# Test artifacts
.coverage
coverage.xml
htmlcov/
```

- [ ] **Step 2: 创建 `backend/Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1.7

# === builder stage ===
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build essentials for any wheels needing compilation (psycopg2-binary 实际不需要但有些 wheels 需要)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install into a --user prefix for cleaner copy in next stage
RUN pip install --user --no-cache-dir --no-warn-script-location -r requirements.txt

# === runtime stage ===
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH=/root/.local/bin:$PATH

# Copy installed packages from builder
COPY --from=builder /root/.local /root/.local

# Copy application code
COPY app/ /app/

EXPOSE 8000

# Run uvicorn directly (matches app_main.py's __main__ block)
CMD ["python", "app_main.py"]
```

- [ ] **Step 3: 验证 backend image 能 build**

```bash
cd "D:/桌面/大模型/agent实战/第六周/industry-research-assistant"
docker build -t test-backend:local backend/ 2>&1 | tail -20
```

Expected: 最后看到 `Successfully built` / `Successfully tagged test-backend:local`，无 error。

> Wall ~4 min on first run (pip install 重)。如果失败看报错；常见是 requirements 漏包 → 回 Task 1 补。

- [ ] **Step 4: 快速测一下 backend image 启动正常（不连 DB 也得起来）**

```bash
docker run --rm -d --name test-backend-run -p 8001:8000 test-backend:local
sleep 3
curl -s http://localhost:8001/hello
docker logs test-backend-run 2>&1 | tail -10
docker stop test-backend-run
```

Expected: `{"status":"success","message":"Hello World! ..."}` from curl。logs 里可能有 DB 连接报错（没 postgres）—— 接受。`/hello` 是不连 DB 的简单端点，必须通。

---

## Task 3: Frontend Dockerfile + .dockerignore + nginx.conf

**Files:**
- Create: `frontend/nginx.conf`
- Create: `frontend/Dockerfile`
- Create: `frontend/.dockerignore`

- [ ] **Step 1: 创建 `frontend/nginx.conf`**

```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # SPA fallback: 任何未匹配的路径都返回 index.html 让 React Router 处理
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API 代理：所有 /api/* 转发到 backend 容器
    location /api/ {
        proxy_pass http://backend:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE 支持（deep research 是流式接口）
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 1800s;
    }

    # 静态资源缓存
    location ~* \.(?:css|js|woff2?|svg|png|jpg|jpeg|gif|ico)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # gzip 压缩
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;
    gzip_min_length 1000;
}
```

- [ ] **Step 2: 创建 `frontend/.dockerignore`**

```
node_modules/
dist/
.vite/
.eslintcache

# Local dev / secrets
.env
.env.*
!.env.example

# Editor / OS
.vscode/
.idea/
.DS_Store
Thumbs.db

# Git
.git/
.gitignore

# Logs
*.log

# Tests
coverage/
.nyc_output/
```

- [ ] **Step 3: 创建 `frontend/Dockerfile`**

```dockerfile
# syntax=docker/dockerfile:1.7

# === builder stage ===
FROM node:20-alpine AS builder

WORKDIR /build

# Copy lockfile + package.json first for layer caching
COPY package.json package-lock.json ./

RUN npm ci --ignore-scripts --legacy-peer-deps

# Copy rest of frontend source
COPY . .

# Build production bundle
RUN npm run build

# === runtime stage ===
FROM nginx:alpine

# Replace default nginx config
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built static files
COPY --from=builder /build/dist /usr/share/nginx/html

EXPOSE 80

# nginx:alpine 默认 CMD 就是启动 nginx，不需要覆盖
```

- [ ] **Step 4: 验证 frontend image 能 build**

```bash
cd "D:/桌面/大模型/agent实战/第六周/industry-research-assistant"
docker build -t test-frontend:local frontend/ 2>&1 | tail -20
```

Expected: 最后 `Successfully built` / `Successfully tagged test-frontend:local`。

Wall ~2 min on first run。

- [ ] **Step 5: 快速测试 nginx 跑得起来（脱离 compose 上下文，nginx /api proxy 会 502，但首页能拿到）**

```bash
docker run --rm -d --name test-frontend-run -p 8002:80 test-frontend:local
sleep 2
curl -sI http://localhost:8002/ | head -5
docker stop test-frontend-run
```

Expected: `HTTP/1.1 200 OK` + `Content-Type: text/html`。

---

## Task 4: 根 docker-compose.yml

**Files:**
- Create: `docker-compose.yml`（项目根目录）

- [ ] **Step 1: 创建 `docker-compose.yml`**

```yaml
# 完整应用栈：postgres + redis + milvus + backend + frontend
# 本地开发：docker compose up -d
# 部署：同一 compose 在服务器上拉 GHCR 镜像跑

services:
  postgres:
    image: postgres:16-alpine
    container_name: industry-postgres
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-postgres}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres123}
      POSTGRES_DB: ${POSTGRES_DB:-industry_assistant}
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    volumes:
      - postgres-data:/var/lib/postgresql/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-postgres}"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - industry-network

  redis:
    image: redis:7-alpine
    container_name: industry-redis
    volumes:
      - redis-data:/data
    ports:
      - "${REDIS_PORT:-6379}:6379"
    restart: unless-stopped
    command: redis-server --save 60 1 --loglevel warning
    networks:
      - industry-network

  milvus-etcd:
    container_name: industry-milvus-etcd
    image: quay.io/coreos/etcd:v3.5.5
    environment:
      - ETCD_AUTO_COMPACTION_MODE=revision
      - ETCD_AUTO_COMPACTION_RETENTION=1000
      - ETCD_QUOTA_BACKEND_BYTES=4294967296
      - ETCD_SNAPSHOT_COUNT=50000
    volumes:
      - milvus-etcd-data:/etcd
    command: etcd -advertise-client-urls=http://127.0.0.1:2379 -listen-client-urls http://0.0.0.0:2379 --data-dir /etcd
    healthcheck:
      test: ["CMD", "etcdctl", "endpoint", "health"]
      interval: 30s
      timeout: 20s
      retries: 3
    networks:
      - industry-network

  milvus-minio:
    container_name: industry-milvus-minio
    image: minio/minio:RELEASE.2023-03-20T20-16-18Z
    environment:
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin
    ports:
      - "9001:9001"
      - "9000:9000"
    volumes:
      - milvus-minio-data:/minio_data
    command: minio server /minio_data --console-address ":9001"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 30s
      timeout: 20s
      retries: 3
    networks:
      - industry-network

  milvus-standalone:
    container_name: industry-milvus-standalone
    image: milvusdb/milvus:v2.3.3
    command: ["milvus", "run", "standalone"]
    environment:
      ETCD_ENDPOINTS: milvus-etcd:2379
      MINIO_ADDRESS: milvus-minio:9000
    volumes:
      - milvus-data:/var/lib/milvus
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9091/healthz"]
      interval: 30s
      start_period: 90s
      timeout: 20s
      retries: 3
    ports:
      - "${MILVUS_PORT:-19530}:19530"
      - "9091:9091"
    depends_on:
      - milvus-etcd
      - milvus-minio
    networks:
      - industry-network

  backend:
    image: ghcr.io/jhzhang2736/industry-research-assistant-backend:latest
    build:
      context: ./backend
    container_name: industry-backend
    env_file: backend/.env
    environment:
      POSTGRES_HOST: postgres
      REDIS_HOST: redis
      MILVUS_HOST: milvus-standalone
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
      milvus-standalone:
        condition: service_started
    ports:
      - "8000:8000"
    restart: unless-stopped
    networks:
      - industry-network

  frontend:
    image: ghcr.io/jhzhang2736/industry-research-assistant-frontend:latest
    build:
      context: ./frontend
    container_name: industry-frontend
    depends_on:
      - backend
    ports:
      - "${FRONTEND_PORT:-80}:80"
    restart: unless-stopped
    networks:
      - industry-network

networks:
  industry-network:
    driver: bridge

volumes:
  postgres-data:
  redis-data:
  milvus-etcd-data:
  milvus-minio-data:
  milvus-data:
```

- [ ] **Step 2: 验证 compose 文件语法**

```bash
docker compose config 2>&1 | head -5
```

Expected: 输出展开后的 yaml（无错误就 OK）。如果报错按报错改。

---

## Task 5: 本地 smoke 全栈

- [ ] **Step 1: 确保 `backend/.env` 存在（compose 要用）**

```bash
ls backend/.env
```

如果没有，从 `.env.example` 复制：

```bash
cp backend/.env.example backend/.env
# 然后手动填入实际 API keys（DASHSCOPE_API_KEY / BOCHA_API_KEY / DEEPSEEK_API_KEY 等）
```

> 这一步 API keys 不填值也能让容器起来，只是研究功能会调不通 LLM。`/hello` 端点不依赖 keys。

- [ ] **Step 2: 启动全栈**

```bash
docker compose up -d
```

Expected: 看到 6 个容器（postgres / redis / milvus-etcd / milvus-minio / milvus-standalone / backend / frontend）创建并启动。Wall ~3-5 min（包含 image build + Milvus startup）。

- [ ] **Step 3: 等待 health check 稳定**

```bash
sleep 30
docker compose ps
```

Expected: 所有 service `STATUS=running`，有 healthcheck 的显示 `healthy`。

> Milvus startup 慢，可能需要再等 60s。重跑 `docker compose ps` 观察。

- [ ] **Step 4: 验证 backend `/hello`**

```bash
curl -s http://localhost:8000/hello
```

Expected: `{"status":"success","message":"Hello World! The API is working correctly."}`

- [ ] **Step 5: 验证 frontend 首页 + API proxy**

```bash
curl -sI http://localhost/ | head -3
curl -s http://localhost/api/hello
```

Expected:
- 首页 `HTTP/1.1 200 OK`
- `/api/hello` 返回同样的 JSON（nginx proxy 通了）

- [ ] **Step 6: 看 backend 日志确认能连 DB**

```bash
docker compose logs backend 2>&1 | grep -E "应用启动|connection|connected|error" | head -10
```

Expected: 看到 `应用启动中...` 没有持续的 connection error。

- [ ] **Step 7: 停掉全栈**

```bash
docker compose down
```

> 不加 `-v` 保留 volumes（postgres-data 等）以便下次启动更快。

---

## Task 6: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/docker.yml`

- [ ] **Step 1: 创建 `.github/workflows/docker.yml`**

```yaml
name: Docker

on:
  push:
    branches: [main]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: false

jobs:
  build-backend:
    name: Build & push backend image
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository_owner }}/industry-research-assistant-backend
          tags: |
            type=raw,value=latest
            type=sha,prefix=sha-,format=short

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: ./backend
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=registry,ref=ghcr.io/${{ github.repository_owner }}/industry-research-assistant-backend:buildcache
          cache-to: type=registry,ref=ghcr.io/${{ github.repository_owner }}/industry-research-assistant-backend:buildcache,mode=max

  build-frontend:
    name: Build & push frontend image
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository_owner }}/industry-research-assistant-frontend
          tags: |
            type=raw,value=latest
            type=sha,prefix=sha-,format=short

      - name: Build and push
        uses: docker/build-push-action@v5
        with:
          context: ./frontend
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=registry,ref=ghcr.io/${{ github.repository_owner }}/industry-research-assistant-frontend:buildcache
          cache-to: type=registry,ref=ghcr.io/${{ github.repository_owner }}/industry-research-assistant-frontend:buildcache,mode=max
```

- [ ] **Step 2: 验证 YAML 语法**

```bash
cd "D:/桌面/大模型/agent实战/第六周/industry-research-assistant"
python -c "import yaml; yaml.safe_load(open('.github/workflows/docker.yml')); print('docker.yml OK')"
```

Expected: `docker.yml OK`

- [ ] **Step 3: 在 GitHub repo 上确认 Actions 有 write 权限到 packages**

打开浏览器 → repo Settings → Actions → General → "Workflow permissions"

确保选中 **"Read and write permissions"**，并保存。

> 如果不勾，第一次 push 镜像会因 `403 denied: permission_denied: write_package` 失败。

---

## Task 7: Commit + push + verify Actions

**前提：** 在新分支做，不直接 commit 到 main。

- [ ] **Step 1: 起新分支**

```bash
cd "D:/桌面/大模型/agent实战/第六周/industry-research-assistant"
git checkout main
git pull
git checkout -b ci/docker-images
```

- [ ] **Step 2: stage 所有改动**

```bash
git add backend/Dockerfile backend/.dockerignore backend/requirements.txt \
        frontend/Dockerfile frontend/.dockerignore frontend/nginx.conf \
        docker-compose.yml \
        .github/workflows/docker.yml \
        docs/superpowers/specs/2026-05-27-docker-images-design.md \
        docs/superpowers/plans/2026-05-27-docker-images-implementation.md
# 这两个是删除（Task 1 中 git rm staged 过了，但 status 可能仍可见）
git add -u backend/app/requirements.txt backend/app/Dockerfile

git status --short
```

Expected: 11 个 `A` / `M` / `D`。

- [ ] **Step 3: commit**

```bash
git commit -m "$(cat <<'EOF'
ci: Docker 镜像构建 + push 到 GHCR (子项目 B)

新增 .github/workflows/docker.yml：
- push to main 触发
- 两个并行 job: build-backend + build-frontend
- 每个 job: buildx + login GHCR (GITHUB_TOKEN) + build-push-action +
  metadata-action 自动 tag (latest + sha-<7>) + registry cache

新增 backend/Dockerfile (多阶段 builder + runtime, python:3.11-slim)
新增 backend/.dockerignore (排除 __pycache__/.env/.eval.db 等)
新增 frontend/Dockerfile (多阶段 node:20-alpine → nginx:alpine)
新增 frontend/.dockerignore (排除 node_modules/dist 等)
新增 frontend/nginx.conf (SPA fallback + /api/* proxy to backend:8000,
  SSE 友好的 proxy_buffering off + 1800s 超时)
新增 docker-compose.yml (根目录, 完整应用栈):
- postgres:16-alpine (新增，原 compose 缺这个主 DB)
- redis + milvus 三件套 (沿用 backend/docker-compose-base.yml 内容)
- backend + frontend 串起 image + build 双指向
- healthcheck + depends_on 链路

整理 backend requirements 单 source of truth:
- 删除 backend/app/requirements.txt (内容不完整且与外层冲突，从未真在生产用过)
- 删除 backend/app/Dockerfile (半成品，移到 backend/ 层级重写)
- backend/requirements.txt 合并内层独有且实际用到的包 (按 grep 结果)

本地 smoke 验证: docker compose up -d 后:
- backend /hello 通
- frontend / 首页 200
- frontend /api/hello 通 (nginx proxy 工作正常)

Spec: docs/superpowers/specs/2026-05-27-docker-images-design.md
Plan: docs/superpowers/plans/2026-05-27-docker-images-implementation.md

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: push 分支 + 开 PR**

```bash
git push -u origin ci/docker-images
gh pr create --base main --head ci/docker-images --title "ci: Docker 镜像构建 + push 到 GHCR (子项目 B)" --body "$(cat <<'EOF'
## Summary

- 新增 \`.github/workflows/docker.yml\`: push to main 触发，并行 build + push backend/frontend 镜像到 GHCR
- 新增多阶段 backend/frontend Dockerfile
- 新增根 \`docker-compose.yml\`: 完整应用栈（postgres + redis + milvus + backend + frontend）
- 整理 requirements: 删 \`backend/app/requirements.txt\` 半成品，外层 \`backend/requirements.txt\` 唯一 source
- 删半成品 \`backend/app/Dockerfile\`

## Test Plan

- [ ] PR 上 CI workflow (来自子项目 A) 仍 pass — tsc/eslint/build/pytest 都该绿
- [ ] Merge 后 Docker workflow 触发，两 job 并行 build + push
- [ ] 看 Packages 页面确认 \`industry-research-assistant-backend:latest\` + \`industry-research-assistant-frontend:latest\` 存在
- [ ] 本地 \`docker pull ghcr.io/.../industry-research-assistant-backend:latest\` 能拉
- [ ] \`docker compose up -d\` 用 GHCR image 跑起来，curl 通

## 文档

- Spec: \`docs/superpowers/specs/2026-05-27-docker-images-design.md\`
- Plan: \`docs/superpowers/plans/2026-05-27-docker-images-implementation.md\`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 5: 等 PR 上的 CI（子项目 A 的 ci.yml）跑过**

```bash
gh pr checks --watch
```

Expected: frontend + backend 两个 check 绿。docker.yml 在 PR 上**不**触发（只 push to main 触发）。

- [ ] **Step 6: merge PR**

```bash
gh pr merge --squash --delete-branch
```

或者去 GitHub UI 上手动 merge。

- [ ] **Step 7: 观察 Docker workflow 在 main 上跑**

```bash
sleep 10
gh run list --workflow=docker.yml --limit 1
gh run watch
```

Expected: build-backend + build-frontend 并行，~4-8 min 后两个都绿。

第一次 run 因为没 cache，wall 4-8 min；后续 cache hit 2-3 min。

- [ ] **Step 8: 验证 image 在 GHCR**

```bash
gh api /users/jhzhang2736/packages/container/industry-research-assistant-backend/versions 2>&1 | jq '.[] | {tags: .metadata.container.tags, created: .created_at}' | head -20
```

Expected: 看到至少一个 version，tags 包含 `latest` 和 `sha-<7>`。

---

## Task 8: 本地 pull GHCR 镜像 verify

- [ ] **Step 1: 删掉本地 test image，确保下面是真从 GHCR 拉**

```bash
docker rmi test-backend:local test-frontend:local 2>&1
docker rmi ghcr.io/jhzhang2736/industry-research-assistant-backend:latest 2>&1
docker rmi ghcr.io/jhzhang2736/industry-research-assistant-frontend:latest 2>&1
```

不存在则会报"No such image"，无害。

- [ ] **Step 2: pull 镜像**

```bash
docker pull ghcr.io/jhzhang2736/industry-research-assistant-backend:latest
docker pull ghcr.io/jhzhang2736/industry-research-assistant-frontend:latest
```

Expected: 两个都 pull 成功。

> 如果 image 是 private（默认 push 上去是 private），需要先 `docker login ghcr.io` 或 GitHub Packages → 改为 public。

- [ ] **Step 3: 用 GHCR image 跑全栈**

```bash
cd "D:/桌面/大模型/agent实战/第六周/industry-research-assistant"
git pull  # 确保本地 main 同步
docker compose pull backend frontend  # 强制用 latest GHCR image
docker compose up -d
sleep 30
docker compose ps
```

Expected: 6 个 service running。backend / frontend 走的是 GHCR pull 来的 image。

- [ ] **Step 4: smoke 测试**

```bash
curl -s http://localhost:8000/hello
curl -sI http://localhost/ | head -3
curl -s http://localhost/api/hello
```

Expected: 跟 Task 5 一样的 3 个结果。

- [ ] **Step 5: 关闭**

```bash
docker compose down
```

---

## 验证清单

| # | 项 | 命令 / 步骤 | 期望 |
|---|---|---|---|
| V1 | 后端镜像本地能 build | `docker build backend/` | 成功 |
| V2 | 前端镜像本地能 build | `docker build frontend/` | 成功 |
| V3 | compose 全栈跑得起来 | `docker compose up -d` | 6 service running |
| V4 | backend /hello | `curl localhost:8000/hello` | 200 + JSON |
| V5 | frontend 首页 | `curl -I localhost/` | 200 |
| V6 | nginx proxy | `curl localhost/api/hello` | 200 + JSON |
| V7 | PR 上 CI 仍绿 | gh pr checks | frontend + backend pass |
| V8 | Docker workflow 在 main 上跑 | gh run list | build-backend + build-frontend pass |
| V9 | GHCR 有 image | gh api packages | latest + sha-<7> tag 存在 |
| V10 | 本地拉 GHCR image 能跑 | docker compose pull && up | Task 8 smoke 通过 |

---

## 风险与回滚

| 风险 | 对策 |
|---|---|
| Task 1 grep 漏掉某依赖 | Task 2 Step 3 本地 docker build 会强制验证；崩了补依赖 |
| GHCR 第一次 push 因权限 fail | Task 6 Step 3 提前在 repo Settings 把 Workflow permissions 设为 read+write |
| nginx /api proxy 配错 | Task 5 Step 5 在 smoke 阶段验证 |
| docker compose 启动 Milvus 慢 | Task 5 Step 3 sleep 30 + 必要时再等 60s 后重测 |
| Buildkit cache 第一次没命中 wall 长 | 接受首次 8 min，后续会快 |

**回滚**：

```bash
git revert <commit-hash>
```

回滚后 docker.yml 没了，main 上的镜像还在（GHCR 不会因 commit revert 删旧 image）。手动去 Packages 页面删 image 如需。

---

## Self-Review 检查（plan 作者自检）

- ✅ **Spec 覆盖**：spec §2 "做"项的 9 项每项都对应到 Task：requirements 整理（T1）/ backend Dockerfile + .dockerignore（T2）/ frontend 三件套（T3）/ 根 compose（T4）/ smoke（T5）/ workflow（T6）/ commit + verify（T7-T8）
- ✅ **无 placeholder**：每个 Step 都有具体命令 / 文件完整内容 / 期望输出
- ✅ **Type 一致性**：service 名 `postgres` / `redis` / `milvus-standalone` / `backend` / `frontend` 在 compose 各处统一；image 名 `industry-research-assistant-{backend,frontend}` 在 workflow 和 compose 一致
- ✅ **路径一致性**：build context 显式 `./backend` / `./frontend`，跟 Dockerfile 内 COPY 路径对应
- ✅ **风险点**（Task 6 Step 3 GHCR 权限手动配置）已显式提示
- ✅ **YAGNI**：multi-arch / cosign / trivy / compose CI smoke 都在 §6 "后续"明确划走
