# CI PR 质量护栏 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 GitHub Actions 上引入 PR 时刻的前端 tsc/eslint/build + 后端 pytest 质量护栏，把现有 `eval.yml` 重复的 unit-tests job 剥离。

**Architecture:** 新增 `.github/workflows/ci.yml`，两个并行 job（frontend + backend）跑在 ubuntu-latest 上；触发于 PR to main 和 push to main。同时改动 `eval.yml` 移除重复的 unit-tests job，让 eval.yml 只保留手动 4h 全套 eval-suite。

**Tech Stack:** GitHub Actions, actions/setup-node@v4 (Node 20 + npm cache), actions/setup-python@v5 (Python 3.11 + pip cache), npm ci, pytest, eslint, vite build

**Spec Reference:** `docs/superpowers/specs/2026-05-27-ci-pr-quality-gates-design.md`

---

## File Structure

| 文件 | 操作 | 责任 |
|---|---|---|
| `.github/workflows/ci.yml` | **新建** | PR/push to main 时的 frontend + backend 质量检查 |
| `.github/workflows/eval.yml` | **修改** | 移除 unit-tests job，保留 eval-suite (workflow_dispatch) |

无其他文件改动。

---

## 执行顺序

```
Task 1  本地 baseline 检查（catch 现有代码问题，避免 CI 第一次跑就红）
Task 2  创建 .github/workflows/ci.yml
Task 3  修改 .github/workflows/eval.yml（移除 unit-tests job + pull_request 触发）
Task 4  Commit + push，验证 Actions 通过
```

---

## Task 1: 本地 baseline 检查

**目的：** CI 第一次跑红得有意义（揭示真问题），而不是揭示 "现有代码本来就有 eslint 错"。先在本地确认 4 个检查都过得去，再合 CI workflow。

**Files:** 无文件修改，纯验证。

- [ ] **Step 1：进入 frontend 目录，确保依赖装了**

```bash
cd "D:/桌面/大模型/agent实战/第六周/industry-research-assistant/frontend"
ls node_modules/.package-lock.json 2>&1 | head -1
```

Expected: 列出文件或显示 No such file。如果没装，跑 `npm install --ignore-scripts --legacy-peer-deps`。

- [ ] **Step 2：TypeScript 类型检查**

```bash
npx tsc --noEmit
```

Expected: 退出码 0，无输出。

**如果失败：** 看报错信息修复 TS 类型问题再继续。这一步不应失败，因为 refactor PR 已经过这关。

- [ ] **Step 3：ESLint 检查**

```bash
npm run lint
```

Expected: 退出码 0，或者列出 warnings/errors。

**如果失败：** 这是最可能失败的一步（现有代码可能从未 lint 过）。两种选择：
1. 修复所有 errors（推荐，本任务一并做掉）
2. 在 `frontend/eslint.config.js` 或类似配置里加 `.eslintignore` 临时跳过有问题的文件，记录 TODO 后续清理

选 1 还是 2 看 errors 数量。20 条以下逐个修，超过则选 2 + 单独项目清理。

- [ ] **Step 4：Vite 生产构建**

```bash
npm run build
```

Expected: 看到 `✓ built in XXXms`，生成 `dist/` 目录。

**如果失败：** 通常是 import 路径错或 TS 类型在 prod mode 才发现的问题。按报错修。

- [ ] **Step 5：后端 pytest**

```bash
cd "D:/桌面/大模型/agent实战/第六周/industry-research-assistant/backend"
pytest app/eval/tests/ -v --tb=short
```

Expected: 全部 PASS。

**如果失败：** 看报错；可能是缺 env var 等环境问题。CI 上跑的 eval/tests/ 是 mock-based 不需要 API key，本地缺也应该 PASS。

- [ ] **Step 6：4 项全过后，准备进 Task 2**

记录 baseline：4 项都过 → Task 2 直接合 CI 配置；任何一项过不了 → 先修复或在本任务里做"清理基线 commit"。

---

## Task 2: 创建 ci.yml

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1：创建 ci.yml**

文件内容（完整，照搬）：

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  frontend:
    name: Frontend (tsc + eslint + build)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
          cache-dependency-path: frontend/package-lock.json

      - name: Install dependencies
        working-directory: frontend
        run: npm ci --ignore-scripts --legacy-peer-deps

      - name: TypeScript check
        working-directory: frontend
        run: npx tsc --noEmit

      - name: ESLint
        working-directory: frontend
        run: npm run lint

      - name: Build
        working-directory: frontend
        run: npm run build

  backend:
    name: Backend (pytest eval/tests)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
          cache-dependency-path: backend/requirements.txt

      - name: Install dependencies
        working-directory: backend
        run: pip install -r requirements.txt

      - name: Run pytest
        working-directory: backend
        run: pytest app/eval/tests/ -v --tb=short
```

- [ ] **Step 2：验证 YAML 语法**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
```

Expected: 退出码 0，无错误。

如果项目无 PyYAML 或不想装，可跳过此步 —— Actions 服务器端会校验。

---

## Task 3: 修改 eval.yml

**Files:**
- Modify: `.github/workflows/eval.yml`

- [ ] **Step 1：读现状**

```bash
cat .github/workflows/eval.yml
```

确认包含 `unit-tests` job (line 20-35 in current version)。

- [ ] **Step 2：用以下内容**整体替换** `.github/workflows/eval.yml`**

```yaml
name: Eval

on:
  workflow_dispatch:
    inputs:
      suite:
        description: 'Suite name (full / mini / <path>)'
        default: 'full'
        required: true
      concurrency:
        description: 'Parallel runs'
        default: '5'
        required: true

jobs:
  eval-suite:
    name: Run full eval suite
    runs-on: ubuntu-latest
    # 30 cases × ~25min/case ÷ 5 concurrency = ~150min + judge/url-check overhead;
    # 4h hard cap gives buffer for slow LLM days.
    timeout-minutes: 240
    env:
      DASHSCOPE_API_KEY: ${{ secrets.DASHSCOPE_API_KEY }}
      DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
      XIAOMI_API_KEY: ${{ secrets.XIAOMI_API_KEY }}
      BOCHA_API_KEY: ${{ secrets.BOCHA_API_KEY }}
      LANGSMITH_API_KEY: ${{ secrets.LANGSMITH_API_KEY }}
      LANGSMITH_PROJECT: industry-research-eval
      POSTGRES_URL: ${{ secrets.POSTGRES_URL }}
      REDIS_URL: ${{ secrets.REDIS_URL }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install deps
        working-directory: backend
        run: pip install -r requirements.txt
      - name: Run eval
        working-directory: backend
        run: |
          python -m app.eval.cli run \
            --suite ${{ inputs.suite }} \
            --concurrency ${{ inputs.concurrency }}
      - name: Upload markdown report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: eval-report
          path: backend/docs/eval-results/*
```

变化点对比原文件：
- 移除 `pull_request` 触发块（unit-tests 没了，no PR-time trigger needed）
- 移除整个 `unit-tests` job（让 ci.yml 的 backend job 接管）
- 移除 eval-suite 的 `if: github.event_name == 'workflow_dispatch'`（现在只剩 workflow_dispatch 触发，条件冗余）

- [ ] **Step 3：验证 YAML 语法**

```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/eval.yml'))"
```

Expected: 退出码 0。

---

## Task 4: Commit + push + 验证

**前提：** 在一个新的分支上做这件事，不直接在 main 上 commit。Refactor PR 还在 review，独立。

- [ ] **Step 1：从 main 起新分支**

```bash
cd "D:/桌面/大模型/agent实战/第六周/industry-research-assistant"
git checkout main
git pull
git checkout -b ci/pr-quality-gates
```

> 如果你在 refactor worktree 里做的，则在那个 worktree 起子分支也行 —— 但更干净的做法是新建 worktree 隔离。

- [ ] **Step 2：把改动 stage + commit**

```bash
git add .github/workflows/ci.yml .github/workflows/eval.yml
git status --short
```

Expected: 
```
A  .github/workflows/ci.yml
M  .github/workflows/eval.yml
```

```bash
git commit -m "$(cat <<'EOF'
ci: 新增 PR 质量护栏 (tsc + eslint + build + pytest)

新增 .github/workflows/ci.yml：
- pull_request to main 和 push to main 触发
- frontend job: tsc --noEmit + eslint + vite build（with npm ci cache）
- backend job: pytest app/eval/tests/（with pip cache）
- 两 job 并行，预估 wall ~2.5 min（cache hit）/ ~4 min（miss）
- Concurrency group cancel-in-progress for PRs

改动 .github/workflows/eval.yml：
- 移除 unit-tests job（重复，ci.yml backend job 接管）
- 移除 pull_request 触发（unit-tests 是唯一 PR-time consumer）
- eval.yml 现只保留 manual 4h 全套 eval-suite

不在本次范围（后续子项目）：
- Docker 镜像构建 + push（子项目 B）
- 自动部署（子项目 C）
- 后端 ruff/mypy（需先清理现有代码 lint 基线）

Spec: docs/superpowers/specs/2026-05-27-ci-pr-quality-gates-design.md
Plan: docs/superpowers/plans/2026-05-27-ci-pr-quality-gates-implementation.md
EOF
)"
```

- [ ] **Step 3：push 分支**

```bash
git push -u origin ci/pr-quality-gates
```

- [ ] **Step 4：开 PR**

```bash
gh pr create --base main --head ci/pr-quality-gates --title "ci: PR 质量护栏 (tsc + eslint + build + pytest)" --body "$(cat <<'EOF'
## Summary

- 新增 .github/workflows/ci.yml: frontend (tsc/eslint/build) + backend (pytest) 双 job 并行
- 改动 .github/workflows/eval.yml: 移除重复的 unit-tests job
- 预估 PR CI wall: ~2.5-4 min

## Test Plan

- [ ] 这个 PR 自己作为第一次 CI run，验证 workflow 配置正确
- [ ] Actions 页面看到 CI workflow 跑起来，frontend 和 backend 两个 job 并行
- [ ] 两个 job 都 ✅ 绿
- [ ] Merge 后建议手动去 Settings → Branches 把 `frontend` 和 `backend` 加为 required status checks

## 文档

- Spec: docs/superpowers/specs/2026-05-27-ci-pr-quality-gates-design.md
- Plan: docs/superpowers/plans/2026-05-27-ci-pr-quality-gates-implementation.md
EOF
)"
```

- [ ] **Step 5：观察 Actions 页面**

打开 PR URL 或 Actions 页面，等 ~3-5 min。

Expected:
- 看到 "CI" workflow 触发
- `frontend` 和 `backend` 两个 job 并行启动
- 都 ✅ 绿
- "Eval" workflow **不**触发（因为已移除 pull_request 触发）

- [ ] **Step 6：处理失败（如果 CI 红）**

最常见失败原因 + 修复：

| 失败 | 原因 | 修复 |
|---|---|---|
| frontend tsc 报错 | Task 1 step 2 漏改东西 | 本地 `npx tsc --noEmit` 复现 + 修 |
| frontend eslint 报错 | Task 1 step 3 没解决干净 | 同上 |
| frontend build 报错 | `vite build` 路径或环境变量问题 | 本地 `npm run build` 复现 |
| backend pytest 报错 | 缺 env var 或 import 链问题 | 看 CI log，本地复现 |
| `npm ci` 报错 cannot find package | lockfile 和 package.json 不同步 | 本地 `npm install` 重新生成 lockfile + 提交 |

修完 push 到同分支，CI 自动重跑。

- [ ] **Step 7：CI 绿了，merge PR**

```bash
gh pr merge --squash --delete-branch
```

或在 GitHub web UI 上点 merge。

---

## 分支保护（手动，非本 plan 自动化范围）

CI 绿了之后，去 GitHub → Settings → Branches → main → Add rule（或 Edit rule）：

1. 勾选 "Require status checks to pass before merging"
2. 在搜索框里加：
   - `frontend`
   - `backend`
3. 可选勾选 "Require branches to be up to date before merging"
4. Save

之后任何 PR 必须 CI 通过才能 merge。

---

## 验证清单（执行完整体的 sanity check）

| # | 项 | 命令 / 步骤 | 期望 |
|---|---|---|---|
| V1 | 本地基线干净 | Task 1 全部 6 步 | 4 项检查全 pass |
| V2 | ci.yml YAML 合法 | `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"` | exit 0 |
| V3 | eval.yml YAML 合法 | 同上 | exit 0 |
| V4 | CI 在 PR 上触发 | 打开 PR，看 Actions tab | "CI" workflow 出现 |
| V5 | frontend 绿 | Actions | ✅ |
| V6 | backend 绿 | Actions | ✅ |
| V7 | eval.yml 不在 PR 上触发 | 同上 | "Eval" workflow 不出现 |
| V8 | Branch protection（可选）| GitHub Settings UI | required checks: frontend + backend |

---

## 风险与回滚

| 风险 | 对策 |
|---|---|
| 第一次 CI 红得太厉害 | Task 1 本地预检已最大化预防；万一漏了，按 Step 6 表格修 |
| 现有代码 lint 错过多 | 在 Task 1 Step 3 决策点选 .eslintignore 临时跳过 + 后续单独项目清理 |
| eval.yml 改动破坏 manual 4h 跑 | eval-suite job 内容未动，只删了 conditional 和 unit-tests，4h 跑功能保留 |

**回滚**：

```bash
git revert <commit-hash>
```

回滚后 main 又没 CI 护栏了，但至少不会卡 review。

---

## Self-Review 检查（plan 作者自检）

- ✅ Spec 覆盖：spec §2 "做" 项全部 6 项（ci.yml + 4 检查 + 缓存 + concurrency）都对应到 Task 2 的 yaml 内容
- ✅ 无 placeholder：每个 step 都有具体命令 + 期望输出
- ✅ Type 一致性：workflow 名 `CI` / `Eval` / job 名 `frontend` / `backend` 全篇统一
- ✅ 路径一致性：`frontend/` 和 `backend/` 工作目录使用 `working-directory` 显式声明，与项目结构对齐
- ✅ Task 1 (pre-flight) 重要性：可能被跳过但 spec 明确风险（"第一次 CI 红得有意义"），plan 已强调
