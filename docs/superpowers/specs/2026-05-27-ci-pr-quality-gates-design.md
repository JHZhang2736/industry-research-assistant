# CI PR 质量护栏设计

> 日期：2026-05-27
> 类型：CI/CD 基础设施 — 子项目 A（共 3 个：A. CI 护栏 / B. Docker 镜像 / C. 自动部署）
> 状态：设计稿，待实施

---

## 1. 背景与动机

项目当前 CI 状况：

- 唯一存在的 workflow `.github/workflows/eval.yml` 只在 `backend/app/eval/**` 或 `backend/requirements.txt` 改动时触发
- 无任何 PR 时刻的前端 lint / typecheck / build 检查
- 无后端非 eval 代码的检查（deep_research_v2 / routers / services / models）

**问题暴露**：刚刚 merge 的 30 文件 refactor（删行业垂直框架）按现有 CI 配置**不会被任何 workflow 拦到**。前端 TS 类型错误、ESLint 违规、Vite prod 构建失败全靠肉眼 review 兜底，回归风险极高。

**本子项目目标**：在 PR 上引入快速反馈的质量护栏（< 5 min wall），**不引入新测试编写工作**（现有代码尚无可补测试的清晰范围）。

---

## 2. 范围

### 做

- 新增 `.github/workflows/ci.yml`，触发于：
  - `pull_request` 到 main
  - `push` 到 main（兜底直接 push 场景）
- **frontend job**：`npx tsc --noEmit` + `npm run lint` + `npm run build`
- **backend job**：`pytest backend/app/eval/tests/ -v --tb=short`
- npm + pip 缓存（基于 lockfile 哈希）
- Concurrency group：同分支新 push 取消未完成 run

### 不做（YAGNI / 后续子项目）

- ❌ Docker 镜像构建 / push → 子项目 B
- ❌ 自动部署 → 子项目 C
- ❌ 后端 ruff/mypy lint → 现有代码上来报一堆错，需要单独项目先清理基线
- ❌ Path filter（基于改动文件跳过 job） → PR 频率低，省的 CI 分钟数不值过早优化
- ❌ Matrix 跑多 Node/Python 版本 → 项目固定 Node 20 / Python 3.11
- ❌ Coverage 报告上传 → 当前没人看，加了也没用
- ❌ Lint auto-fix bot → 后期再说

---

## 3. 设计决策

### 3.1 两个 job 并行（而非串行）

ubuntu-latest 上 `frontend` 和 `backend` job 各自独立，GitHub Actions 默认并行执行。

- **并行 wall** = max(frontend, backend) ≈ 3-4 min
- **串行 wall** = sum(frontend, backend) ≈ 6-7 min

并行划算。

### 3.2 新建 ci.yml，不合到 eval.yml

`eval.yml` 有专属职责：

- `unit-tests` job：PR 上跑 mock-based eval 测试（当前的 PR 检查唯一一项）
- `eval-suite` job：`workflow_dispatch` 手动触发 4h 全套 30 case eval 跑

把日常 PR lint/build 塞进 eval.yml 会让它变成 god workflow。两文件分职责清晰。

### 3.3 改动 eval.yml：移除 unit-tests job

eval.yml 当前的 `unit-tests` job 在 `backend/app/eval/**` 改动时跑 `pytest app/eval/tests/`。新 ci.yml 的 `backend` job 也跑同一组测试，**且在所有 PR 上跑**。

两个 workflow 在 eval/** 改动 PR 上会重复跑 pytest。解决方案：移除 eval.yml 的 unit-tests job，保留 `eval-suite`。

### 3.4 npm ci + --ignore-scripts + --legacy-peer-deps

- **npm ci**：CI 上强制按 `package-lock.json` 精确装，更快、更可复现（vs `npm install` 可能更新 lockfile）
- **--ignore-scripts**：跳过 `package.json` 的 postinstall `chmod +x node_modules/.bin/* 2>/dev/null || true`。这是 Unix-only 命令，CI 是 ubuntu 上不会 crash，但跳过统一行为（且 Windows dev 已确认该 script 是死代码）
- **--legacy-peer-deps**：项目使用 React 19 + antd 5，存在 peer dep 冲突，需要此 flag

### 3.5 缓存策略

- **npm cache key** = `hashFiles('frontend/package-lock.json')`
- **pip cache key** = `hashFiles('backend/requirements.txt')`

GitHub Actions 的 `actions/setup-node` 和 `actions/setup-python` 内置 cache 支持，只需声明 `cache: 'npm'` / `cache: 'pip'`。

- 命中时：npm ci ≈ 30s，pip install ≈ 20s
- 未命中：npm ci ≈ 2 min，pip install ≈ 1.5 min

### 3.6 Concurrency group + cancel-in-progress

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

同分支连续 push 时，前一次未完成 run 立即取消，省 CI 分钟数。Main push 不取消（保留稳定 baseline 记录）—— 通过 `if: github.event_name == 'pull_request'` 条件实现。

---

## 4. 性能预估（单次 CI run wall time）

| Phase | Cache hit | Cache miss |
|---|---|---|
| checkout | 5s | 5s |
| setup-node + cache restore | 5s | 5s |
| npm ci | 30s | 120s |
| tsc --noEmit | 30s | 30s |
| npm run lint | 15s | 15s |
| npm run build | 60s | 60s |
| **frontend wall** | **~2:25** | **~3:55** |
| setup-python + cache restore | 5s | 5s |
| pip install | 20s | 90s |
| pytest eval/tests | 30s | 30s |
| **backend wall** | **~1:00** | **~2:10** |
| **CI wall (max)** | **~2:25** | **~3:55** |

第一次冷启动 ~4 min，稳定后 ~2.5 min。符合 "< 5 min" 目标。

---

## 5. 分支保护（非本 spec 自动化范围）

第一次 ci.yml run 通过后，建议在 GitHub Settings → Branches → main rule 添加 required status checks：

- `frontend`
- `backend`

这样 PR 未通过 CI 不能 merge。这部分操作只能在 web UI 上点，不在 spec 自动化范围。

---

## 6. 风险与回滚

| 风险 | 概率 | 影响 | 对策 |
|---|---|---|---|
| 现有代码 eslint 报错触发 CI fail | 中 | 第一次 PR 红 | Pre-flight：本地先跑一遍 `npm run lint`，把基线问题解决后再合 ci.yml |
| 现有代码 TS 类型问题 | 低 | CI fail | 上一个 refactor 已跑过 tsc 干净，新代码进 PR 时遇到再修 |
| Vite build 失败（环境变量缺失等） | 低 | CI fail | `vite build` 不需要 `.env` 必填项，已实测可空环境构建 |
| Cache 失效导致 wall 变长 | 低 | wall 4 min → 4 min（仍可接受） | 不动作，cache miss 不是 fail |
| npm registry 慢 | 中 | wall 偶尔涨 | GitHub Actions 自动复用 cache，新依赖才需要拉 |

**回滚**：

- 删 `.github/workflows/ci.yml`
- 在 `eval.yml` 恢复 unit-tests job
- `git revert` 整个 CI commit

---

## 7. 后续（不在本 spec 范围）

- **子项目 B**（Docker 镜像）：写 Dockerfile + image build/push workflow → 给 C 打基础
- **子项目 C**（自动部署）：从 registry 拉镜像部署到指定 host
- **后端 ruff/mypy**：单独项目，需先清理现有代码 lint 基线
- **测试覆盖率上报**：写完更多单元测试后再考虑
- **Lint auto-fix bot**：低优先级
