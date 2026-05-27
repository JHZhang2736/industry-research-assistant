# 自动部署到阿里云 ECS 设计

> 日期：2026-05-27
> 类型：CI/CD 基础设施 — 子项目 C（共 3 个：A. CI 护栏 ✅ / B. Docker 镜像 ✅ / C. 自动部署）
> 状态：设计稿，待实施

---

## 1. 背景与动机

子项目 A、B 已落地。镜像已自动 build push 到 GHCR：

- `ghcr.io/jhzhang2736/industry-research-assistant-backend:latest`
- `ghcr.io/jhzhang2736/industry-research-assistant-frontend:latest`

子项目 C 目标：merge 到 main 后**全自动部署**到用户的阿里云 ECS，不需要任何手动 SSH 操作。

**部署目标信息：**

- 阿里云 ECS：**8C16G + Ubuntu**，公网可达
- Docker 已装，docker-compose 已装
- 现状：跑着 `backend/docker-compose-base.yml` 的 base 版本（Redis + Milvus，无 Postgres / backend / frontend）
- 无域名（http://IP:port 访问，无 TLS）
- 用户决策：**首次部署全推倒重来**，接受丢失旧 Milvus 知识库数据

---

## 2. 范围

### 做

- 新增 `.github/workflows/docker.yml` 里的 `deploy` job（不新建独立 workflow）
- 触发链：`push to main → build-backend + build-frontend → deploy job`
- SSH key 认证（新生成 deploy-only ed25519 keypair，4 个 GitHub Secrets）
- ECS 上约定的项目目录 `/opt/industry-research-assistant/`
- 首次部署的 onboarding 文档（一次性手动操作）
- 部署脚本：git pull → docker compose pull → docker compose up -d
- 镜像 public 化（GHCR 上手动设置，文档说明流程）

### 不做（YAGNI / 后续）

- ❌ 零停机部署（rolling update / blue-green）— 个人项目可接受 30s 重启
- ❌ Health check 失败自动回滚 — 简单部署，回滚靠手动 `docker compose pull <旧 sha>`
- ❌ 部署前先跑 smoke 测试 — 镜像 build 阶段已经测过
- ❌ TLS / Let's Encrypt — 无域名暂不做
- ❌ 阿里云 ACR 同步镜像加速国内拉取 — 先用 GHCR 看实测速度
- ❌ Slack / 飞书部署通知 — 后续可加
- ❌ 部署日志归档到对象存储 — 用 GitHub Actions log 足够

---

## 3. 设计决策

### 3.1 单 workflow 加 deploy job vs 双 workflow

候选：

| 方式 | 优点 | 缺点 |
|---|---|---|
| **A. 在 docker.yml 加 deploy job**（采纳） | 单一 workflow，依赖链 build→deploy 用 `needs:` 直接表达，调试时一个页面看全 | 文件长一点 |
| B. 新建 deploy.yml，用 `workflow_run` 触发 | 职责分离 | workflow_run 触发延迟、调试两个页面跳来跳去 |

选 A。

### 3.2 SSH key 用 deploy-only ed25519，不复用日常 key

最小权限原则。新生成一对 deploy 专用 key，丢失也只影响这一台 ECS 的 deploy 流。日常 key 不进 GitHub Secrets。

ed25519 比 RSA 短且安全。

### 3.3 4 个 GitHub Secrets

| Secret 名 | 内容 | 来源 |
|---|---|---|
| `SSH_PRIVATE_KEY` | deploy key 私钥（PEM 格式整段） | 本地 `ssh-keygen` 生成 |
| `SSH_HOST` | ECS 公网 IP | 阿里云控制台 |
| `SSH_USER` | SSH 登录用户名 | 用户决定（root / ubuntu / 自建） |
| `SSH_PORT` | SSH 端口 | 默认 22，如果改了写自定义 |

### 3.4 不做动态 IP 白名单

GitHub Actions runner IP 段几百个、频繁变化。维护成本高，对个人项目过度设计。

策略：22 端口（或自定义）对 0.0.0.0/0 开放，但**仅允许 SSH key 认证**（`sshd_config` 设 `PasswordAuthentication no`）。

### 3.5 项目目录 `/opt/industry-research-assistant/`

Linux 惯例：第三方应用放 `/opt/`。也可以放 `~/`，但 `/opt/` 多人维护时更清晰。

`docker-compose.yml` 和 `backend/.env` 都从这个目录读取。

### 3.6 `backend/.env` 不进 git，首次手动配

`backend/.env` 含 API keys（DASHSCOPE / DEEPSEEK / BOCHA 等）。**绝不进 git**。

首次部署 onboarding：用户在 ECS 上 `cp backend/.env.example backend/.env` + 手填实际 key。之后 workflow 不动 `.env`，只 `git pull` 同步代码 + `docker compose pull` 拉新镜像。

后续 `.env` 改动靠用户手动改（小项目接受）。

### 3.7 GHCR 镜像设为 public

**理由**：
- ECS 拉镜像不需要 `docker login` → workflow 步骤少一个 Secret
- 个人项目天然透明，没有商业敏感性
- 拉取速度更稳定（public image 不受 rate limit）

**用户手动操作一次**：去 https://github.com/users/JHZhang2736/packages 把两个 package 设为 public（Settings → "Change visibility" → Public）。

如果后续想转 private：加 `GHCR_PAT` Secret + workflow 加 `docker login` 步骤即可。

### 3.8 部署脚本用 SSH heredoc 不用 action

候选：
- **A. `ssh user@host << 'EOF' ... EOF`**（采纳）—— 4 行 bash，透明，可读
- B. `appleboy/ssh-action@v1` —— 封装了细节，但要学一套 yaml 参数

A 更直接，调试时直接 copy bash 命令到本地 SSH 验证。

### 3.9 部署接受 30s 停机

部署步骤 `docker compose up -d` 会重启 backend + frontend（image 变了），中间有 ~30s 服务不可用。个人项目可接受，不做 rolling / blue-green。

### 3.10 首次部署 onboarding 不自动化

需要用户手动做的事：

1. 阿里云控制台：22 端口安全组开 0.0.0.0/0
2. ECS：`sshd_config` 设 `PasswordAuthentication no`（如未设）
3. ECS：把 deploy public key 加到 `~/.ssh/authorized_keys`
4. ECS：`docker compose -f backend/docker-compose-base.yml down -v`（拆掉旧 base）
5. ECS：`git clone <repo> /opt/industry-research-assistant && cd $_ && cp backend/.env.example backend/.env && vim backend/.env`
6. GitHub：把 4 个 Secrets 加进 repo settings
7. GitHub：Packages 页面把两个镜像设为 Public

自动化这些会引入复杂度（chmod 权限、idempotency、首次 vs 再次的判断），且只跑一次。文档化为 plan 任务即可。

---

## 4. Workflow 流程图

```
push to main
    │
    ├─ job: build-backend (已有，sub-project B)
    ├─ job: build-frontend (已有，sub-project B)
    │
    └─ job: deploy
         │
         ├─ checkout
         ├─ Install SSH key (shimataro/ssh-key-action@v2)
         ├─ Add ECS to known_hosts (ssh-keyscan)
         ├─ SSH to ECS + heredoc:
         │     cd /opt/industry-research-assistant
         │     git pull
         │     docker compose pull backend frontend
         │     docker compose up -d --remove-orphans
         │     docker compose ps  # 看健康状态
         │
         └─ done
```

---

## 5. 性能与成本预估

| 阶段 | 时长 |
|---|---|
| build-backend wall | ~4 min (cache miss) / ~2 min (hit) |
| build-frontend wall | ~3 min / ~1.5 min |
| deploy job wall | ~1-2 min（取决于 ECS pull 镜像速度 + restart）|
| **总 main → 生产可用** | **~5-8 min（cache miss）/ ~3-5 min（hit）** |

如果 GHCR → 阿里云 ECS 拉镜像很慢（实测过 50 MB/s 以下），后续考虑加 ACR mirror。

---

## 6. 风险与回滚

| 风险 | 对策 |
|---|---|
| SSH 认证失败（key 拷错 / 端口未开） | Onboarding 文档每步明确，第一次手动跑通 `ssh -i ~/.ssh/gha-deploy user@host` 才进 workflow |
| ECS 上 `docker compose pull` 慢/超时 | 接受现状；workflow 默认无 timeout 限制，10 min 内绝对完成 |
| 第一次部署：postgres init 慢导致 backend health check 失败 | compose 里已有 `depends_on: postgres: condition: service_healthy`，会自动等 |
| 镜像 build 失败时 deploy job 仍跑（导致部署旧 sha） | `needs: [build-backend, build-frontend]` 默认要求前置 job success；不需要额外保护 |
| ECS 磁盘满（多版本镜像累积） | 加 `docker image prune -a -f --filter "until=168h"` 作为 deploy 后清理（保留 7 天内的）|
| 首次部署忘记设 .env | 文档明确这步；backend 容器没 .env 会 crash loop，看 `docker compose logs backend` 一目了然 |

**回滚步骤**（手动）：

```bash
# SSH 到 ECS
ssh user@host
cd /opt/industry-research-assistant
# 把 latest 指向旧 sha
docker pull ghcr.io/jhzhang2736/industry-research-assistant-backend:sha-<old>
docker tag ghcr.io/.../backend:sha-<old> ghcr.io/.../backend:latest
docker compose up -d
```

更优雅的回滚是用 `:sha-<7>` tag 修改 docker-compose.yml 后 commit + push，但那要 round-trip 一次 main，慢。手动 retag 更快。

---

## 7. 后续（不在本 spec 范围）

- ACR mirror（如果 GHCR 拉太慢）
- 域名 + TLS（绑域名后 + Let's Encrypt）
- Slack/飞书部署通知
- 零停机部署（要先做 backend 多实例 + reverse proxy 负载均衡）
- 回滚自动化（在 workflow 里加 manual workflow_dispatch 选 sha）
- 阿里云 RDS / Redis 托管服务（成本权衡）
