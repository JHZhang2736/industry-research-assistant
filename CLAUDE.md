# 项目说明：信息行业分析助手（DeepResearch）

## 项目定位
多智能体协作的 AI 深度研究系统，自动完成从信息收集、数据分析到报告撰写的完整研究流程。

## 目标用户
- 行业分析师
- 投资研究人员
- 企业战略部门

## 核心能力
通过多智能体协作，端到端完成深度研究任务，覆盖信息收集 → 数据分析 → 报告撰写全链路。

## 应用场景

### 1. 行业研究报告生成
- 快速调研行业市场规模、竞争格局、技术趋势
- 输出符合投行标准的深度研究报告

### 2. 企业竞争分析
- 分析特定企业的市场地位、业务模式、财务表现
- 横向对比多个竞争对手

### 3. 政策影响评估
- 追踪政策变化对行业的影响
- 预测政策趋势

### 4. 技术趋势研判
- 识别新兴技术的发展阶段
- 评估技术成熟度与商业化前景

## 系统架构

### 前端
React 18 + TypeScript + Ant Design + ECharts + Recharts + react-markdown + Zustand + Axios

### API 网关层（FastAPI）
| 模块 | 接口 |
|------|------|
| `/auth` | `POST /login`、`POST /register`、`GET /me` |
| `/research` | `POST /start`（SSE）、`POST /cancel`、`GET /checkpoint/:session_id`、`POST /resume/:session_id` |
| `/knowledge` | `POST /create`、`POST /upload`、`GET /list`、`DELETE /:kb_id` |
| `/database` | `GET /tables`、`POST /query`（Text2SQL）、`GET /schema/:table_name` |
| `/news` | `GET /list`、`GET /:news_id` |
| `/memory` | `GET /list`、`GET /:session_id` |

### 业务层
- **多智能体编排引擎**：LangGraph
- **辅助服务**：
  - Text2SQL（数据库查询）
  - 新闻采集（定时任务）
  - 知识库管理（向量检索）

### 数据存储层
- **关系型数据库**：PostgreSQL（业务数据、会话、用户；LangGraph 官方 PostgresSaver 提供 checkpoint 持久化）
- **向量数据库**：Milvus（知识库向量检索）
- **缓存**：Redis（会话、限流、热点数据）
- **对象存储**：MinIO（原始文档、报告产物；同时作为 Milvus 的 S3 后端）

## 技术特征
- 架构：多智能体（Multi-Agent）协作，基于 LangGraph 编排
- 形态：AI 深度研究系统（Deep Research），支持 SSE 流式输出与断点续跑（checkpoint/resume）
- 工作流：信息收集 → 数据分析 → 报告撰写

---

# Git 协作规范

> 本节是 **强约束**。Claude Code 在本项目工作时必须严格遵守。

## 0. 核心原则

| 编号 | 规则 | 例外 |
|------|------|------|
| R1 | **禁止直接 push 到 `main`** | 无 |
| R2 | **所有变更通过 Pull Request 合并** | 无 |
| R3 | **PR 由用户审核合并**，Claude 不自行合并 | 用户在当次对话明确说"自行合并" |
| R4 | **禁止 force push 到 `main` 或共享分支** | 用户明确授权 |
| R5 | **禁止 `--no-verify` 跳过 hooks**、`--no-gpg-sign` 跳过签名 | 用户明确授权 |
| R6 | **禁止在未授权下做破坏性操作**（`reset --hard`、`branch -D`、`push --force`、`clean -fd`） | 用户明确授权 |

## 1. 分支策略

### 1.1 主分支
- `main`：始终保持可发布状态，受保护，仅通过 PR 合并

### 1.2 工作分支命名
格式：`<type>/<short-kebab-description>`

| type | 用途 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat/agent-orchestrator` |
| `fix` | Bug 修复 | `fix/sse-disconnect` |
| `docs` | 文档变更 | `docs/api-reference` |
| `chore` | 构建/依赖/工具链 | `chore/upgrade-langgraph` |
| `refactor` | 重构（无行为变化） | `refactor/extract-llm-client` |
| `test` | 仅测试 | `test/research-flow-e2e` |
| `perf` | 性能优化 | `perf/vector-search-cache` |
| `ci` | CI/CD 配置 | `ci/add-pytest-workflow` |
| `build` | 构建系统 | `build/dockerize-backend` |
| `hotfix` | 紧急生产修复 | `hotfix/auth-token-leak` |

### 1.3 分支生命周期
1. 从最新 `main` 切出：`git switch main && git pull && git switch -c <type>/<desc>`
2. 完成开发并自测
3. 推到 origin：`git push -u origin <branch>`
4. 开 PR
5. 合并后**删除远端与本地分支**：`git branch -d <branch>` + `git push origin --delete <branch>`

## 2. 提交规范（Conventional Commits）

### 2.1 格式
```
<type>(<scope>): <subject>

<body>

<footer>
```

- **type**：与分支 type 一致（feat / fix / docs / chore / refactor / test / perf / ci / build）
- **scope**：可选，影响范围，如 `backend`、`docker`、`agent`、`api`
- **subject**：祈使句，**英文小写起头**（"add" 而不是 "Added"），不加句号，≤ 72 字符
- **body**：可选，解释 *why*，每行 ≤ 100 字符
- **footer**：可选，关联 issue / breaking change

### 2.2 示例

```
feat(agent): add LangGraph supervisor for research workflow

Wire the supervisor node so it can route between collector, analyzer,
and writer agents. Uses Postgres checkpointer for resume.

Refs #12
```

```
fix(api): prevent SSE connection leak on client disconnect
```

```
chore(deps): bump langgraph from 0.2.x to 0.3.x
```

### 2.3 提交粒度
- 一个 commit 解决一个**逻辑变更**
- 不把无关变更打进同一个 commit
- 调试性 commit（`wip`、`fixup`）允许在分支内存在，但**合 PR 前用 squash 或 rebase 清理**

## 3. Pull Request 规范

### 3.1 标题
与首个 commit 的 subject 同风格：`<type>(<scope>): <subject>`

### 3.2 描述模板
```markdown
## Summary
- 用 2-4 个 bullet 说明本次改动核心
- 强调 *why* 而不是逐行 *what*

## Changes
- 关键文件 / 模块的变化点

## Test plan
- [ ] 手动验证步骤 1
- [ ] 单元/集成测试覆盖
- [ ] 关联组件回归

## Notes (可选)
- 已知问题、后续待办、设计权衡说明
```

### 3.3 PR 大小
- **目标 ≤ 400 行变更**（不含 lockfile / 自动生成文件）
- 超过 800 行需在描述里解释为什么不能拆
- 大重构与功能开发分开 PR

### 3.4 关联事项
- 关联 issue 用 `Closes #N` / `Refs #N`
- Breaking change 在 footer 注明 `BREAKING CHANGE: <说明>`

## 4. 合并策略

| 场景 | 策略 | 理由 |
|------|------|------|
| 普通功能 / Bug 修复 | **Squash and merge** | 保持 main 线性、每个 PR 一个 commit |
| 多 commit 有独立价值的重构 | Rebase and merge | 保留中间步骤但避免 merge 提交 |
| 长期分支同步主干 | `git rebase main`（**不用 merge main**） | 保持 PR 历史干净 |

**不使用 GitHub 默认的 "Create a merge commit"**。

## 5. 代码审核

- PR 必须至少 1 个 Approve 才能合并（用户即为唯一审核人时由用户合并）
- CI（lint / 测试 / 类型检查）必须全绿
- Conversation 必须全部 resolve
- 自审 Checklist：
  - [ ] 自己再过一遍 diff，删掉调试代码、TODO 和无关变更
  - [ ] 新功能附了测试或在 PR 描述里说明为什么不需要
  - [ ] 没有提交密钥 / `.env` / 生产凭据
  - [ ] CLAUDE.md 与 README 必要时同步更新

## 6. Claude Code 工作流速查

每次开始改代码前，Claude 必须先执行：

```bash
git status                       # 确认 working tree 干净
git switch main && git pull      # 同步最新 main
git switch -c <type>/<desc>      # 切新分支
```

完成后：

```bash
git add <specific files>         # 避免 git add . 误带敏感文件
git commit -m "<conventional>"   # 不用 --no-verify
git push -u origin <branch>
gh pr create --title "..." --body "$(cat <<'EOF' ... EOF)"
```

**绝不**：
- `git push origin main`
- `git push --force` 到任何共享分支
- `git commit --amend` 已推送的 commit
- 在 main 上直接修改文件

## 7. 紧急情况

若用户明确要求"绕过规则"（如紧急修复直接推 main），Claude 应：
1. 复述用户的指令以确认
2. 执行并在回复中明示"按你的要求绕过 R1 规则"
3. 完成后建议立即补回正常流程（如开补丁 PR 把变更搬到分支并 squash）
