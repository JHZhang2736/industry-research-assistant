# 自动部署到阿里云 ECS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `docker.yml` 加 `deploy` job，merge 到 main 后自动 SSH 进阿里云 ECS 拉新镜像 + restart docker compose，实现完整 CI/CD 闭环。

**Architecture:** 在 sub-project B 的 docker.yml 末尾加 deploy job（`needs: [build-backend, build-frontend]`）；通过 SSH key + 4 个 GitHub Secrets 认证；deploy 步骤 = `git pull` + `docker compose pull` + `docker compose up -d`。镜像设为 public，ECS 拉取无需 GHCR token。

**Tech Stack:** GitHub Actions, SSH (ed25519 key), shimataro/ssh-key-action@v2, Docker Compose, 阿里云 ECS (Ubuntu)

**Spec Reference:** `docs/superpowers/specs/2026-05-27-deploy-to-ecs-design.md`

---

## File Structure

| 文件 | 操作 | 责任 |
|---|---|---|
| `.github/workflows/docker.yml` | **改** | 在末尾追加 deploy job |
| `docs/superpowers/specs/2026-05-27-deploy-to-ecs-design.md` | 已存在 | spec |
| `docs/superpowers/plans/2026-05-27-deploy-to-ecs-implementation.md` | 已存在 | 本 plan |

无其他文件改动。所有手动 onboarding 操作（ECS 端、GitHub Secrets、Packages 可见性）记录在 plan 任务里供用户执行。

---

## 执行顺序

```
Task 1   [手动] 阿里云 / ECS 准备（SSH key 生成、authorized_keys、安全组、sshd_config）
Task 2   [手动] 老 base stack 推倒（docker compose -f backend/docker-compose-base.yml down -v）
Task 3   [手动] ECS 上 git clone repo + 准备 backend/.env
Task 4   [手动] GitHub Secrets 配 4 个（SSH_PRIVATE_KEY / SSH_HOST / SSH_USER / SSH_PORT）
Task 5   [手动] GitHub Packages 两个 image 改为 Public
Task 6   [代码] 改 docker.yml 加 deploy job
Task 7   [代码] Commit + push + 开 PR + 验证
Task 8   [手动] Merge → 看自动部署 → 访问 http://ECS_IP/ 验证
```

> Task 1-5 是首次 onboarding，**只跑一次**，后续部署完全自动。

---

## Task 1: ECS 端准备

### 在本地（你的 Windows 机器）

- [ ] **Step 1：生成 deploy-only ed25519 keypair**

```bash
ssh-keygen -t ed25519 -f ~/.ssh/gha-deploy -N "" -C "github-actions-deploy"
```

`-N ""` 是空 passphrase（workflow 不能交互输入密码）。`-C` 是注释方便日后识别。

生成两个文件：
- `~/.ssh/gha-deploy`（**私钥**，下一步给 GitHub Secret）
- `~/.ssh/gha-deploy.pub`（**公钥**，下一步给 ECS）

- [ ] **Step 2：查看公钥内容**

```bash
cat ~/.ssh/gha-deploy.pub
```

复制完整一行 `ssh-ed25519 AAAA... github-actions-deploy` 备用。

### 在 ECS 上（SSH 登录后）

- [ ] **Step 3：把公钥加到 authorized_keys**

```bash
# SSH 登录 ECS
ssh your-user@your-ecs-ip

# 追加公钥（不要覆盖现有的）
echo "ssh-ed25519 AAAA... github-actions-deploy" >> ~/.ssh/authorized_keys

# 权限检查
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
```

- [ ] **Step 4：禁用密码登录（强烈建议）**

```bash
sudo vim /etc/ssh/sshd_config
```

确认下面三行的值：

```
PermitRootLogin prohibit-password    # 或 yes，看你是否用 root 登录
PasswordAuthentication no
PubkeyAuthentication yes
```

如果改了任何值：

```bash
sudo systemctl reload sshd
```

- [ ] **Step 5：阿里云控制台 → 安全组 → 入方向**

确认 22 端口（或你自定义的 SSH 端口）的入方向规则放开 `0.0.0.0/0`。

> 注意：放开 22 端口看起来"危险"，但因为已经 `PasswordAuthentication no`，没有 key 的人连不上。GitHub Actions IP 段太大没法精确白名单。

### 在本地验证 deploy key 能登录

- [ ] **Step 6：用新 key 登录一次**

```bash
ssh -i ~/.ssh/gha-deploy your-user@your-ecs-ip -p 22
```

Expected：直接进 ECS 终端，没有密码提示。如果提示密码，说明 Step 3/4 没做对。

> 这步是 onboarding gate。第一次手动跑通了，Workflow 才有可能成功。**Step 6 不通**不要进 Task 6。

退出 ECS：`exit`

---

## Task 2: 推倒老 base stack

### 在 ECS 上

- [ ] **Step 1：找到老 base 的位置**

```bash
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
```

Expected：看到 `document-redis` / `milvus-etcd` / `milvus-minio` / `milvus-standalone` 这些 container 在跑。

```bash
docker compose ls
```

看到对应的 compose project 名 + 工作目录。

- [ ] **Step 2：到那个工作目录 down**

```bash
cd <对应 compose project 路径>
docker compose -f docker-compose-base.yml down -v
```

`-v` 是关键 —— 同时删除 volume。

Expected：4 个 container 全部停止 + 移除，volume 也清空。

- [ ] **Step 3：确认干净**

```bash
docker ps
docker volume ls | grep -E "redis-data|milvus-"
```

Expected：`docker ps` 看不到上面那些 container；`docker volume ls` 不再有 redis-data / milvus-* 相关 volume。

---

## Task 3: ECS 上 clone 项目 + 准备 .env

### 在 ECS 上

- [ ] **Step 1：clone 仓库到 /opt**

```bash
sudo mkdir -p /opt
sudo chown $(whoami):$(whoami) /opt
cd /opt
git clone https://github.com/JHZhang2736/industry-research-assistant.git
cd industry-research-assistant
```

- [ ] **Step 2：检出 main 分支最新**

```bash
git checkout main
git pull
```

Expected：包含子项目 A、B 的所有 commit。

- [ ] **Step 3：准备 backend/.env**

```bash
cp backend/.env.example backend/.env
vim backend/.env
```

填入实际值：
- `DASHSCOPE_API_KEY=` 你的百炼 key
- `BOCHA_API_KEY=` 你的博查 key
- `DEEPSEEK_API_KEY=` 你的 DeepSeek key
- `JWT_SECRET_KEY=` 生成一个随机字符串（如 `openssl rand -hex 32`）
- `POSTGRES_HOST=postgres`（compose 服务名，不是 localhost）
- `REDIS_HOST=redis`
- `MILVUS_HOST=milvus-standalone`
- 其他保持默认或按需调整

保存退出。

> **⚠️ POSTGRES_HOST / REDIS_HOST / MILVUS_HOST 必须用 compose 服务名**，因为这是 backend 容器内的视角，需要走 compose 网络解析。

- [ ] **Step 4：验证文件存在**

```bash
ls -la backend/.env
```

Expected：文件存在，权限 644 或更严。

---

## Task 4: GitHub Secrets 配置

### 在 GitHub repo 网页

- [ ] **Step 1：进入 repo Secrets 页**

打开 https://github.com/JHZhang2736/industry-research-assistant/settings/secrets/actions

- [ ] **Step 2：新增 Secret `SSH_PRIVATE_KEY`**

点 "New repository secret"
- Name: `SSH_PRIVATE_KEY`
- Value: 整段私钥内容，包括 `-----BEGIN OPENSSH PRIVATE KEY-----` 和 `-----END OPENSSH PRIVATE KEY-----`

取私钥内容：在本地跑 `cat ~/.ssh/gha-deploy`，全选复制。

- [ ] **Step 3：新增 `SSH_HOST`**

Name: `SSH_HOST`
Value: 你的 ECS 公网 IP，例如 `47.123.45.67`

- [ ] **Step 4：新增 `SSH_USER`**

Name: `SSH_USER`
Value: 你 SSH 登录的用户名（一般 `root` 或 `ubuntu`，看你 ECS 是怎么建的）

- [ ] **Step 5：新增 `SSH_PORT`**

Name: `SSH_PORT`
Value: SSH 端口，默认是 `22`，如果改过填实际值

- [ ] **Step 6：确认 4 个 Secrets 都存在**

页面上应该看到：
- SSH_HOST
- SSH_PORT
- SSH_PRIVATE_KEY
- SSH_USER

---

## Task 5: GitHub Packages 改为 Public

### 在 GitHub Packages 页面

- [ ] **Step 1：进入 backend 镜像页**

打开 https://github.com/users/JHZhang2736/packages/container/industry-research-assistant-backend

- [ ] **Step 2：右下角 "Package settings" → "Change visibility"**

选 "Public"，输入 package 名确认。

- [ ] **Step 3：frontend 镜像同样操作**

打开 https://github.com/users/JHZhang2736/packages/container/industry-research-assistant-frontend

同样操作设为 Public。

- [ ] **Step 4：验证可匿名拉取**

```bash
# 在 ECS 上（不需要先 docker login）
docker pull ghcr.io/jhzhang2736/industry-research-assistant-backend:latest
docker pull ghcr.io/jhzhang2736/industry-research-assistant-frontend:latest
```

Expected：两个都能成功 pull，无 "unauthorized" 错误。

---

## Task 6: 改 docker.yml 加 deploy job

### 在本地（新分支）

- [ ] **Step 1：从最新 main 起新分支**

```bash
cd "D:/桌面/大模型/agent实战/第六周/industry-research-assistant"
git checkout main
git pull
git checkout -b ci/deploy-to-ecs
```

- [ ] **Step 2：在 `.github/workflows/docker.yml` 末尾追加 deploy job**

打开 `.github/workflows/docker.yml`，在 `build-frontend` job 后追加（注意保持 2 空格缩进与文件其他 job 一致）：

```yaml

  deploy:
    name: Deploy to ECS
    needs: [build-backend, build-frontend]
    runs-on: ubuntu-latest
    steps:
      - name: Install SSH key
        uses: shimataro/ssh-key-action@v2
        with:
          key: ${{ secrets.SSH_PRIVATE_KEY }}
          known_hosts: 'placeholder-will-replace'

      - name: Add ECS to known_hosts
        run: |
          ssh-keyscan -H -p ${{ secrets.SSH_PORT }} ${{ secrets.SSH_HOST }} >> ~/.ssh/known_hosts

      - name: Deploy via SSH
        run: |
          ssh -p ${{ secrets.SSH_PORT }} ${{ secrets.SSH_USER }}@${{ secrets.SSH_HOST }} << 'EOF'
            set -e
            cd /opt/industry-research-assistant
            echo "=== Sync repo ==="
            git pull origin main
            echo "=== Pull new images ==="
            docker compose pull backend frontend
            echo "=== Restart stack ==="
            docker compose up -d --remove-orphans
            echo "=== Status ==="
            docker compose ps
            echo "=== Prune old images (keep 7d) ==="
            docker image prune -a -f --filter "until=168h" || true
          EOF
```

完整文件结构应是：

```yaml
name: Docker
on: ...
concurrency: ...
jobs:
  build-backend: ...     # 已有
  build-frontend: ...    # 已有
  deploy: ...            # 新加
```

- [ ] **Step 3：验证 YAML 语法**

```bash
python -c "import yaml; data = yaml.safe_load(open('.github/workflows/docker.yml')); print('Jobs:', list(data['jobs'].keys()))"
```

Expected: `Jobs: ['build-backend', 'build-frontend', 'deploy']`

- [ ] **Step 4：验证 deploy job 的 needs 配置**

```bash
python -c "import yaml; data = yaml.safe_load(open('.github/workflows/docker.yml')); print(data['jobs']['deploy']['needs'])"
```

Expected: `['build-backend', 'build-frontend']`

---

## Task 7: Commit + PR + verify

- [ ] **Step 1：stage + commit**

```bash
cd "D:/桌面/大模型/agent实战/第六周/industry-research-assistant"
git add .github/workflows/docker.yml docs/superpowers/specs/2026-05-27-deploy-to-ecs-design.md docs/superpowers/plans/2026-05-27-deploy-to-ecs-implementation.md
git status --short
```

Expected: 3 个 staged files (1 M + 2 A)。

```bash
git commit -m "$(cat <<'EOF'
ci: 自动部署到阿里云 ECS (子项目 C)

在 .github/workflows/docker.yml 追加 deploy job：
- needs: [build-backend, build-frontend]
- SSH key 认证 via shimataro/ssh-key-action@v2
- ssh-keyscan 动态加 ECS 到 known_hosts
- SSH heredoc 执行：git pull + docker compose pull + up -d + image prune

需要的 GitHub Secrets：
- SSH_PRIVATE_KEY: deploy-only ed25519 私钥
- SSH_HOST / SSH_USER / SSH_PORT: ECS 连接信息

镜像在 GHCR 设为 public，ECS 拉镜像无需 docker login。

完整 onboarding 步骤（首次手动一次性）见 plan Task 1-5。

Spec: docs/superpowers/specs/2026-05-27-deploy-to-ecs-design.md
Plan: docs/superpowers/plans/2026-05-27-deploy-to-ecs-implementation.md

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 2：push + 开 PR**

```bash
git push -u origin ci/deploy-to-ecs
gh pr create --base main --head ci/deploy-to-ecs --title "ci: 自动部署到阿里云 ECS (子项目 C)" --body "$(cat <<'EOF'
## Summary

- 在 docker.yml 加 deploy job，merge 到 main 后自动 SSH 进阿里云 ECS 拉新镜像 + restart
- needs build-backend + build-frontend，确保镜像 push 完才部署
- 镜像 public, ECS 拉镜像无需 docker login

## Test Plan

- [ ] PR 上子项目 A 的 CI 通过（frontend + backend 静态检查）
- [ ] Onboarding 完成（Task 1-5 全做完）
- [ ] Merge 后 docker.yml 三个 job 顺序 run，最后 deploy job 绿
- [ ] http://ECS_IP/ 看到前端
- [ ] http://ECS_IP/api/hello 返回正常 JSON

## 文档

- Spec: \`docs/superpowers/specs/2026-05-27-deploy-to-ecs-design.md\`
- Plan: \`docs/superpowers/plans/2026-05-27-deploy-to-ecs-implementation.md\`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3：等 PR CI 跑过**

```bash
gh pr checks --watch
```

Expected: `frontend` + `backend` 两个 check 绿（来自子项目 A 的 ci.yml）。docker.yml 在 PR 上不触发（只 on main）。

---

## Task 8: Merge → 验证自动部署

- [ ] **Step 1：手动验证所有 Onboarding 都完成**

回 Task 1-5 检查每个 checkbox，全勾才进 Step 2。

任何一个没勾，merge 后 deploy 一定失败。

- [ ] **Step 2：Merge PR**

```bash
gh pr merge --squash --delete-branch
```

或 GitHub UI 点 merge。

- [ ] **Step 3：观察 Actions 页面 docker.yml 跑**

```bash
gh run list --workflow=docker.yml --limit 1
gh run watch
```

Expected:
- build-backend ✅（~3-4 min）
- build-frontend ✅（~2-3 min）
- deploy ✅（~1-2 min）

总 wall ~5-8 min。

- [ ] **Step 4：访问验证**

浏览器打开 `http://ECS_IP/`。

Expected：
- 看到 AI 深度研究助手首页（4 个研究模板卡片）
- 左侧 6 项菜单
- 进 `/chat` 输入框正常

curl 验证：

```bash
curl http://ECS_IP/api/hello
```

Expected：`{"status":"success","message":"Hello World! ..."}`

- [ ] **Step 5：跑一次完整研究 smoke**

浏览器进 `/chat`，输入 `AI 大模型 2024 市场规模与主要厂商`，发送。

Expected：
- 看到 6 阶段 SSE 流式事件（Plan / Scout / Analyze / Wizard / Write / Review）
- 最终生成研究报告

> 这步可能要 26 min，可以等也可以信任前面单测过了直接通过 Task 8。

- [ ] **Step 6：故障排查（如果 deploy job 红）**

最常见问题：

| 失败 | 排查 |
|---|---|
| `Permission denied (publickey)` | Task 1 Step 3-4 没做对；SSH_PRIVATE_KEY 复制不完整 |
| `Connection refused` | 安全组没开 22 端口；或 SSH_PORT 写错 |
| `Host key verification failed` | known_hosts 步骤失败，可能是 SSH_HOST IP 写错 |
| `git pull` 报错 | ECS 上 /opt/industry-research-assistant 不是 git repo / 没 main 分支 |
| `docker compose pull` 报 unauthorized | Task 5 镜像没设为 public |
| `backend` 容器一直 restart | backend/.env 没配 / API key 错；`docker compose logs backend` 看 |

修完直接 push 一个 fix commit 到 main，会自动重跑。

---

## 验证清单

| # | 项 | 命令 / 步骤 | 期望 |
|---|---|---|---|
| V1 | 本地 SSH 用 deploy key 进 ECS | Task 1 Step 6 | 不要密码直接进 |
| V2 | ECS 上老 base 全清 | Task 2 Step 3 | docker ps 无 milvus/redis container |
| V3 | ECS 上有 /opt 项目目录 + .env | Task 3 | ls 看到 |
| V4 | 4 个 Secrets 都配 | Task 4 Step 6 | GitHub Secrets 页可见 |
| V5 | 镜像可匿名 pull | Task 5 Step 4 | docker pull 不报 unauthorized |
| V6 | docker.yml 含 deploy job | Task 6 Step 3 | jobs 列表有 deploy |
| V7 | PR CI 绿 | Task 7 Step 3 | frontend + backend pass |
| V8 | Merge 后 deploy job 绿 | Task 8 Step 3 | 三 job 全绿 |
| V9 | http://ECS_IP/ 首页 | Task 8 Step 4 | 200 + 看到 UI |
| V10 | /api/hello 通 | Task 8 Step 4 | JSON |

---

## 风险与回滚

| 风险 | 对策 |
|---|---|
| 第一次 deploy 失败 | Task 8 Step 6 表逐项排查 |
| ECS 拉 GHCR 镜像慢 | 接受；测过实在不行后续 spec ACR mirror |
| .env 配错导致 backend crash loop | docker compose logs 即时可见；改 .env 后 docker compose up -d 重启即可 |
| 部署中间 30s 停机 | 个人项目接受 |
| 一周后磁盘满 | image prune --filter "until=168h" 已经在 deploy 脚本里 |

**回滚**：

```bash
# SSH 进 ECS
ssh -i ~/.ssh/gha-deploy your-user@ECS_IP
cd /opt/industry-research-assistant

# 找上一个能用的 sha（GitHub Packages 页面看 tags）
docker pull ghcr.io/jhzhang2736/industry-research-assistant-backend:sha-<old>
docker pull ghcr.io/jhzhang2736/industry-research-assistant-frontend:sha-<old>

# 临时改 docker-compose.yml 的 image: tag 为 :sha-<old>，或者 retag
docker tag ghcr.io/jhzhang2736/industry-research-assistant-backend:sha-<old> ghcr.io/jhzhang2736/industry-research-assistant-backend:latest
docker tag ghcr.io/jhzhang2736/industry-research-assistant-frontend:sha-<old> ghcr.io/jhzhang2736/industry-research-assistant-frontend:latest
docker compose up -d
```

或更彻底：`git checkout <old-commit>` + `docker compose up -d`，强制本地状态退回。

---

## Self-Review 检查（plan 作者自检）

- ✅ **Spec 覆盖**：spec §2 "做"项的 8 条全部对应 Task：workflow 改动（T6）/ SSH 认证（T1）/ Secrets（T4）/ ECS onboarding（T2-T3）/ 镜像 public（T5）/ 部署脚本（T6）
- ✅ **无 placeholder**：每个 Step 都有具体命令 + 期望输出 + 失败时如何排查
- ✅ **Type 一致性**：Secret 名 SSH_PRIVATE_KEY / SSH_HOST / SSH_USER / SSH_PORT 全篇统一；image 名 `industry-research-assistant-{backend,frontend}` 跟 sub-project B 一致
- ✅ **手动 vs 自动边界清晰**：Task 1-5 显式标记为 onboarding 一次性手动，Task 6-8 为代码自动化部分
- ✅ **Onboarding gate**：T1 Step 6（本地用 deploy key 登 ECS）是 onboarding 必须通过的 gate，避免后续 workflow 失败时不知道是哪一步问题
- ✅ **YAGNI**：rolling deploy / TLS / ACR mirror / Slack 通知都明确划走到后续
