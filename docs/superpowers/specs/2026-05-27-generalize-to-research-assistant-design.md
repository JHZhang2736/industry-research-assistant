# 从「行业研究助手」改造为通用 AI 深度研究助手

> 日期：2026-05-27
> 类型：定位调整 + 大范围功能删除
> 状态：设计稿，待执行

---

## 1. 背景与动机

### 1.1 当前定位的问题

项目当前以**"行业研究助手"**为对外定位，前端硬编码了 4 个垂直行业（智慧交通 / 金融科技 / 医疗健康 / 能源电力），后端围绕这些行业配套了：

- 行业资讯采集服务（BOCHA 搜索 API + APScheduler 每日 12 点定时任务 + Postgres 落地）
- 招投标信息采集（阿里云市场招投标 API）
- 行业资讯展示页、招投标展示页
- 全局行业切换器（导航栏 Dropdown，行业 id 存 localStorage）

### 1.2 "行业"是个空壳

但仔细看代码，**6-Agent deep research 引擎本身与行业无关**：

- 所有 Agent 的 prompt 模板（ChiefArchitect / DeepScout / DataAnalyst / CodeWizard / LeadWriter / CriticMaster）都通用
- Critic 的 7 维评审标准（relevance / coherence / citation / completeness / ...）都通用
- Writer 的章节生成逻辑都通用
- 切换"智慧交通"和"医疗健康"，唯一的实际差异是 `INDUSTRY_CONFIGS` 里几组关键词 —— 用于资讯/招投标采集时的搜索 query 预设

换句话说，"行业"是一层**薄薄的关键词预设皮**，没有真正影响研究方法。

### 1.3 为什么决定拆掉

- **没有领域 know-how 支撑**：开发者本身不具备智慧交通 / 金融科技 / 医疗 / 能源电力 4 个领域的产业研究经验，无法回答"你为这 4 个行业各自设计了什么不同的研究方法"
- **"伪垂直"是负资产**：作品集 / 演示场景下被问起来会很尴尬
- **核心技术深度被遮蔽**：真正能打的卖点是多 Agent 协同 + Critic 自反思 + 并行优化（26→15 min）+ 7 维 ensemble evaluator + LangGraph 0.2+ + SSE 流式，这些都是**行业无关的技术能力**

### 1.4 新定位

**"AI 深度研究助手"** —— 用户输入任意研究主题，系统通过 6-Agent 协同 + 多轮 Critic 反思自动产出 6,000+ 字的研究报告。

技术差异化点：
- 多 Agent 协同（非单 prompt 折叠）
- Critic 自我反思 + 多轮 revise
- 并行优化（Scout 7×、Writer 5.4× wall 缩减）
- 7 维 ensemble judge 自动评测
- LangGraph 原生 + PG checkpoint 状态持久化
- SSE 流式过程可视化

---

## 2. 改造范围总览

| 类别 | 数量 | 备注 |
|---|---|---|
| 后端文件**整体删除** | 6 | router / 4 个 service+config / 1 个 model |
| 后端 in-place 修改 | 2 | `app_main.py`, `models/__init__.py` |
| 前端文件/目录**整体删除** | 7 | pages / store / api / components / mock data |
| 前端 in-place 修改 | 5 | routes / nav / api index / 首页 / 聊天页 |
| 数据库 drop 表 | 3 | `industry_news` / `bidding_info` / `news_collection_tasks` |
| 配置清理 | 2+ | `.env.example`, `requirements.txt` |

**保留不动**：
- Deep research 引擎（`backend/app/service/deep_research_v2/`）
- Chat / 对话历史 / 知识库 / 数据库查询页
- 用户 / 会话 / 记忆 / 研究 checkpoint 表
- BOCHA API key（deep research scout 也用它）
- 仓库名 `industry-research-assistant`（git 仓库名不改）

---

## 3. 详细删除清单

### 3.1 后端整体删除

| 路径 | 作用 |
|---|---|
| `backend/app/router/news_router.py` | 资讯/招投标 HTTP API |
| `backend/app/service/news_collection_service.py` | 资讯采集核心服务 |
| `backend/app/service/bidding_service.py` | 招投标 API 调用 |
| `backend/app/service/scheduler_service.py` | APScheduler 每日采集任务 |
| `backend/app/config/industry_config.py` | 4 个行业 + 关键词预设 |
| `backend/app/models/news.py` | IndustryNews / BiddingInfo / NewsCollectionTask 3 个 ORM 模型 |

### 3.2 前端整体删除

| 路径 | 作用 |
|---|---|
| `frontend/src/pages/news/` 整目录 | 行业资讯页 |
| `frontend/src/pages/bidding/` 整目录 | 招投标页 |
| `frontend/src/pages/chat/component/news.tsx` + `.module.scss` | 聊天页 sidebar mock 新闻 |
| `frontend/src/store/industry.ts` | 全局行业 store + 4 行业配置 |
| `frontend/src/api/news.ts` | 资讯/招投标 API client |
| `frontend/src/components/collection-modal/` 整目录 | 手动采集进度弹窗 |
| `frontend/src/configs/data/news.ts` | mock 新闻数据 |

### 3.3 后端 in-place 修改

**`backend/app/app_main.py`**
- 删 `from router.news_router import router as news_router`
- 删 models import 列表里 `IndustryNews, BiddingInfo, NewsCollectionTask`
- 删 lifespan 里 scheduler 启动 / 关闭两个 try 块
- 删 `app.include_router(news_router)`
- 改 `title="行业信息助手 API"` → `title="深度研究助手 API"`

**`backend/app/models/__init__.py`**
- 删 `from .news import ...`
- 从 `__all__` 删 3 个 news 模型名

### 3.4 前端 in-place 修改

**`frontend/src/router/routes.tsx`**：删 NewsPage / BiddingPage import + 路由项

**`frontend/src/api/index.ts`**：删 `export * as news`

**`frontend/src/layout/base/nav.tsx`**：
- 删 IconNews / IconBid import
- 删整个 `industry-selector` Dropdown 块
- 删 menu items 里 `news` 和 `bid` 两项
- 删 `industryState` / `currentIndustry` 相关代码

**`frontend/src/layout/base/nav.scss`**：删 `.industry-selector` 样式块

**`frontend/src/pages/index/index.tsx`** —— 改造（不删）：
- 卡片数据源从 `INDUSTRY_CONFIGS` 改成 4 个**研究模板**：
  - 市场分析（默认 prompt: `请帮我分析 [行业/产品] 的市场规模、增长趋势和主要参与者`）
  - 竞品研究（默认 prompt: `请对 [公司A] 和 [公司B] 做对比分析，包括产品、技术、市场份额`）
  - 政策解读（默认 prompt: `请解读 [政策名称] 的核心内容、影响范围和企业应对方向`）
  - 技术调研（默认 prompt: `请调研 [技术领域] 的发展现状、主流方案、技术演进方向`）
- 点击卡片 → `navigate('/chat?prompt=' + encodeURIComponent(模板 prompt))`
- 标题：`Hi～欢迎来到行业咨询助手` → `Hi～欢迎使用 AI 深度研究助手`
- 描述改为通用文案
- 现有 `.card-list` SCSS 4 列布局完全复用，无需改样式

**`frontend/src/pages/chat/newchat.tsx`** —— 简化：
- 删除 `industryState` / `currentIndustryName` / `recommendQuestions` 全部
- 删除 sidebar news/bidding API 拉取（`useEffect` + `Promise.all` 块）
- 删除整个 sidebar JSX
- 推荐问题改为静态 3 条通用示例：
  - `AI 大模型 2024 市场规模与主要厂商`
  - `新能源汽车产业链格局与上下游分析`
  - `半导体国产化进展与关键卡点`
- 页面只保留：欢迎语 + 静态推荐问题 + ComSender 输入框

### 3.5 数据库变更

执行 SQL：
```sql
DROP TABLE IF EXISTS industry_news CASCADE;
DROP TABLE IF EXISTS bidding_info CASCADE;
DROP TABLE IF EXISTS news_collection_tasks CASCADE;
```

执行**前**先 `pg_dump` 三张表数据，万一回滚需要：
```bash
pg_dump -h localhost -U postgres -d industry_assistant \
  -t industry_news -t bidding_info -t news_collection_tasks \
  > backup/2026-05-27-news-bidding-tables.sql
```

**保留**的核心表（不动）：
- `users`, `chat_sessions`, `chat_messages`, `chat_attachments`, `long_term_memories`
- `knowledge_bases`, `documents`
- `industry_stats`, `company_data`, `policy_data`（数据库查询页用）
- `research_checkpoints`（LangGraph state）

### 3.6 配置清理

**`backend/.env.example`**：
- 删 `BID_APP_KEY` / `BID_APP_SECRET` / `BID_APP_CODE` 三行
- 删 `JUHE_STOCK_API_KEY`（只在资讯采集间接使用，需先 grep 确认无其他引用）

**`backend/requirements.txt`**：
- 若 `apscheduler` 只被 `scheduler_service` 引用，删除该依赖

---

## 4. 设计决策记录

### 4.1 为什么首页改成「研究模板卡片」而不是「单输入框」？

候选方案：

| 方案 | 优势 | 劣势 |
|---|---|---|
| A. 单大输入框 | 最简洁，改动最小 | 用户冷启动不知道能问什么 |
| **B. 研究模板卡片**（采纳） | 给冷启动用户引导，且模板和"通用研究"定位契合 | 改动量稍大，需要设计 prompt |
| C. 直接 redirect 到 /chat | 极简，首页代码可删 | 首页存在感为零，作品集观感差 |

选 B：保留首页脚手架价值的同时不绑定行业。模板覆盖**研究方法论维度**（市场 / 竞品 / 政策 / 技术），而非垂直行业。

### 4.2 为什么聊天页 sidebar 完全删？

候选方案：

| 方案 | 优势 | 劣势 |
|---|---|---|
| **A. 全删，只留输入框**（采纳） | 最干净，聚焦研究本身 | 失去 sidebar 信息密度 |
| B. 删 sidebar，留静态推荐问题 | 折中 | 静态推荐很快"过期"，仍要维护 |
| C. 改成"研究历史"sidebar | 信息量大 | 和已有"对话历史"抽屉重复 |

选 A：sidebar 的 news/bidding 列表只是装饰性的"行业感"，删除后聊天页变成"专注研究的纯入口"，更符合通用助手定位。

### 4.3 为什么不只是"隐藏"而是"彻底删除"？

候选方案：

| 方案 | 优势 | 劣势 |
|---|---|---|
| **A. 彻底删除**（采纳） | 代码库干净，无死代码 | 不可逆，回滚靠 git revert |
| B. 注释/feature flag 隐藏 | 可逆 | 留下大量死代码，未来维护负担 |
| C. 移到独立分支保留 | 可逆 + 主干干净 | 分支永久占用，维护成本高 |

选 A：本次是**主动战略调整**，不是临时隐藏。死代码会污染未来阅读，且 git revert 完全够用。

---

## 5. 执行顺序

1. **DB 备份**：`pg_dump` 三张表到 `backup/` 目录
2. **后端**：删 6 个文件 + 改 `app_main.py` + 改 `models/__init__.py`
3. **前端**：删 7 处文件/目录 + 改 5 处 in-place（routes / nav / api index / index 页 / newchat 页）
4. **配置清理**：`.env.example` + `requirements.txt`
5. **本地验证**（见 §6）
6. **DB drop**：执行 3 个 DROP TABLE
7. **单一 commit** 提交全部改动

---

## 6. 验证清单

执行完后逐项跑：

| # | 项 | 命令 / 步骤 | 期望 |
|---|---|---|---|
| 1 | 后端启动 | `python backend/app/app_main.py` | 无 import 错误，无 scheduler 启动日志 |
| 2 | 前端启动 | `cd frontend && npm run dev` | 无 TypeScript 报错 |
| 3 | 路由 404 | 访问 `/news`、`/bidding` | 显示 404 页 |
| 4 | 菜单 | 看左侧导航 | 只剩 首页/聊天/历史/记忆/知识库/数据库（6 项），无行业 Dropdown |
| 5 | 首页 | 访问 `/` | 4 个研究模板卡片，点击进 `/chat?prompt=...` 带 prompt |
| 6 | 聊天页 | 访问 `/chat` | 无 sidebar，3 条静态推荐问题，输入框正常 |
| 7 | 端到端研究 | 输入"AI 大模型 2024 市场规模"跑完整轮 | deep research 链路正常，最终产出 6000+ 字报告 |
| 8 | DB | `psql -c "\dt"` | `industry_news` / `bidding_info` / `news_collection_tasks` 消失，其他表都在 |
| 9 | smoke 复跑 | 跑 `parallel-002` 案例 | 相比上一次 26 min 无显著回归 |

---

## 7. 风险与回滚

| 风险 | 概率 | 影响 | 对策 |
|---|---|---|---|
| 误删 BOCHA API key 配置 | 低 | deep research scout 失效 | 只删 `industry_config.py`（关键词预设），不动 `BOCHA_API_KEY` |
| 误删 `industry_data` 模型（数据库查询页用） | 低 | 数据库页空白 | `industry_data.py` 与 `news.py` 是不同文件，只删后者 |
| 找不到的 import 引用 | 中 | 启动报错 | grep 全局确认无遗漏后再启动；启动失败按 stack trace 快速修 |
| DB drop 后想恢复 | 低 | 数据丢失 | 执行前 pg_dump 备份到 `backup/` |
| commit 一团乱影响 review | 低 | 难审查 | 分 2-3 个 commit：(a) 后端删除, (b) 前端删除+改造, (c) 文案 + DB 脚本 |

**回滚机制**：
- 代码：`git revert <commit-hash>`
- 数据库：从 `backup/2026-05-27-news-bidding-tables.sql` restore

---

## 8. 改造后的 README 文案（建议）

`README.md` 和 `frontend/README.md` 应同步更新定位描述：

> **AI 深度研究助手** —— 基于 6-Agent 协同 + Critic 自反思的 LangGraph 应用。用户输入任意研究主题，系统自动产出结构化研究报告（6,000+ 字、含引用）。
>
> 核心技术：
> - 多 Agent 并行：6 章节并行撰写，Scout 查询级并行（wall 7× 缩减）
> - Critic 多轮反思 + revise，最多 3 iteration
> - 7 维 ensemble judge 自动评测（relevance / coherence / citation / ...）
> - LangGraph 0.2+ 原生 + PG checkpoint 状态持久化
> - SSE 流式过程可视化

具体 README 文案改动放后续 PR，不在本次 spec 范围。

---

## 9. 后续（不在本次范围）

执行完本 spec 后，可继续考虑：

1. **README 文案大改**：项目根 README + frontend README 重写定位描述
2. **截图替换**：原 README 里所有带"行业切换器"的截图重拍
3. **`industry_data` 表是否也通用化**：当前 PolicyData / CompanyData 表也带"行业"字段，可后续评估是否拆耦
4. **首页"研究模板"prompt 优化**：4 个模板的默认 prompt 跑过实测后调优
5. **聊天页"研究历史"sidebar**：如果用户需要快速回到历史报告，可后续加（当前对话历史抽屉已经覆盖部分场景）
