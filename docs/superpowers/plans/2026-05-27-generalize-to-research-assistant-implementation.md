# Generalize to Research Assistant — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 拆掉"行业垂直"框架，把项目改造为通用 AI 深度研究助手。

**Architecture:** 删除行业切换器 + 行业资讯页 + 招投标页（含后端服务、定时任务、Postgres 表）；首页改成 4 个通用研究模板卡片；聊天页简化为纯输入框 + 静态推荐问题。Deep research 引擎（6 Agent + Critic + 并行化）原样保留 —— 它本就行业无关。

**Tech Stack:** React + TypeScript + Vite（前端）、FastAPI + LangGraph + PostgreSQL + SQLAlchemy（后端）

**Spec Reference:** `docs/superpowers/specs/2026-05-27-generalize-to-research-assistant-design.md`

---

## File Structure

### 整体删除（13 项）

**后端 6 个文件：**
- `backend/app/router/news_router.py`
- `backend/app/service/news_collection_service.py`
- `backend/app/service/bidding_service.py`
- `backend/app/service/scheduler_service.py`
- `backend/app/config/industry_config.py`
- `backend/app/models/news.py`

**前端 7 处文件/目录：**
- `frontend/src/pages/news/`（整目录）
- `frontend/src/pages/bidding/`（整目录）
- `frontend/src/pages/chat/component/news.tsx` + `news.module.scss`
- `frontend/src/store/industry.ts`
- `frontend/src/api/news.ts`
- `frontend/src/components/collection-modal/`（整目录）
- `frontend/src/configs/data/news.ts`

### In-place 修改（9 个文件）

**后端：**
- `backend/app/app_main.py` —— 删 import / scheduler 启动关闭 / route 注册
- `backend/app/models/__init__.py` —— 删 news 相关 export
- `backend/.env.example` —— 删 BID_APP_* 三件套
- `backend/app/requirements.txt` —— 删 apscheduler

**前端：**
- `frontend/src/router/routes.tsx` —— 删 News/Bidding 路由
- `frontend/src/api/index.ts` —— 删 news export
- `frontend/src/layout/base/nav.tsx` —— 删 industry-selector + news/bid 菜单项
- `frontend/src/layout/base/nav.scss` —— 删 industry-selector 样式
- `frontend/src/pages/index/index.tsx` —— 行业卡片 → 研究模板卡片
- `frontend/src/pages/chat/newchat.tsx` —— 删 sidebar + 推荐问题改静态

### 数据库 drop（3 张表）

- `industry_news`
- `bidding_info`
- `news_collection_tasks`

### 不动（确认范围）

- `backend/app/service/deep_research_v2/` 整套（研究引擎，通用）
- `backend/app/service/stock_service.py`（**仍使用 JUHE_STOCK_API_KEY**，保留）
- `backend/app/models/industry_data.py`（PolicyData / CompanyData / IndustryStats，数据库查询页用）
- 用户 / 会话 / 记忆 / 研究 checkpoint 表
- `BOCHA_API_KEY` / `JUHE_STOCK_API_KEY`（保留）

---

## 执行顺序总览

```
Task 0  DB 备份
Task 1  后端 in-place（先断 import）
Task 2  后端文件删除
Task 3  后端启动验证
Task 4  前端 in-place（先断 import）
Task 5  首页改造
Task 6  聊天页简化
Task 7  前端文件删除
Task 8  前端启动验证 + ts check
Task 9  配置清理
Task 10 DB drop
Task 11 端到端 smoke 验证
Task 12 提交（3 个 commits）
```

**顺序原则**：所有引用方先在 in-place 编辑里去掉对要删文件的 import，再删文件 —— 避免中间状态出现 broken import。

---

## Task 0: DB 备份

**Files:**
- Create: `backend/backup/2026-05-27-news-bidding-tables.sql`

- [ ] **Step 1：检查 Postgres 容器是否在跑**

```bash
docker ps | grep postgres
```

Expected：看到 `postgres` 容器 STATUS=Up。

- [ ] **Step 2：备份 3 张表**

```bash
mkdir -p backend/backup
docker exec -t industry-research-assistant-postgres-1 pg_dump \
  -U postgres -d industry_assistant \
  -t industry_news -t bidding_info -t news_collection_tasks \
  > backend/backup/2026-05-27-news-bidding-tables.sql
```

> 容器名按实际 `docker ps` 输出调整。

Expected：生成的 SQL 文件 size > 0。

- [ ] **Step 3：确认备份非空**

```bash
ls -la backend/backup/2026-05-27-news-bidding-tables.sql
head -20 backend/backup/2026-05-27-news-bidding-tables.sql
```

Expected：看到 `-- PostgreSQL database dump` 头部和 `CREATE TABLE` 语句。

---

## Task 1: 后端 in-place（先断 import）

**Files:**
- Modify: `backend/app/app_main.py`
- Modify: `backend/app/models/__init__.py`

- [ ] **Step 1：修改 `backend/app/app_main.py`**

删除以下内容：
- line 23: `from router.news_router import router as news_router`
- line 29: models import 列表里去掉 `IndustryNews, BiddingInfo, NewsCollectionTask`（保留其他模型）
- line 42-48: 整个 scheduler 启动 try 块
- line 53-59: 整个 scheduler 关闭 try 块
- line 89: `app.include_router(news_router)`

修改：
- line 63: `title="行业信息助手 API"` → `title="深度研究助手 API"`

最终 `lifespan` 函数应变成：

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("应用启动中...")
    yield
    logger.info("应用关闭中...")
```

最终 models import 应变成：

```python
from models import (
    User, ChatSession, ChatMessage, ChatAttachment, LongTermMemory,
    KnowledgeBase, Document, IndustryStats, CompanyData, PolicyData,
    ResearchCheckpoint
)
```

- [ ] **Step 2：修改 `backend/app/models/__init__.py`**

删除 line 8（`from .news import ...`）和 `__all__` 里的 3 个 news 模型名。

最终文件应为：

```python
from .user import User
from .chat import ChatSession, ChatMessage, ChatAttachment, LongTermMemory
from .knowledge import KnowledgeBase, Document
from .industry_data import IndustryStats, CompanyData, PolicyData
from .research import ResearchCheckpoint

__all__ = [
    "User",
    "ChatSession",
    "ChatMessage",
    "ChatAttachment",
    "LongTermMemory",
    "KnowledgeBase",
    "Document",
    "IndustryStats",
    "CompanyData",
    "PolicyData",
    "ResearchCheckpoint",
]
```

- [ ] **Step 3：验证 import 链没有遗漏**

```bash
cd backend
grep -rn "scheduler_service\|news_router\|news_collection_service\|bidding_service\|industry_config\|from models.news\|from .news" app/
```

Expected：只剩下要删除的 6 个文件本身的内部引用，没有其他模块 import 它们。

---

## Task 2: 后端文件删除

**Files:**
- Delete: 6 个后端文件

- [ ] **Step 1：删除 6 个文件**

```bash
rm backend/app/router/news_router.py
rm backend/app/service/news_collection_service.py
rm backend/app/service/bidding_service.py
rm backend/app/service/scheduler_service.py
rm backend/app/config/industry_config.py
rm backend/app/models/news.py
```

- [ ] **Step 2：确认文件已删**

```bash
ls backend/app/router/news_router.py backend/app/service/news_collection_service.py 2>&1 | grep -i "no such"
```

Expected：每行都报"No such file"。

---

## Task 3: 后端启动验证

- [ ] **Step 1：启动后端**

```bash
cd backend/app
python app_main.py
```

Expected：
- 看到 `Uvicorn running on http://0.0.0.0:8000`
- **没有**任何 `ImportError` / `ModuleNotFoundError`
- **没有**任何 "定时任务调度器启动" 日志（旧的）

- [ ] **Step 2：访问 /hello 确认 API 在跑**

```bash
curl http://localhost:8000/hello
```

Expected：`{"status":"success","message":"Hello World! The API is working correctly."}`

- [ ] **Step 3：访问被删的 news 路由确认 404**

```bash
curl -i http://localhost:8000/news/list
```

Expected：`HTTP/1.1 404 Not Found`。

- [ ] **Step 4：停掉后端服务（准备下一步）**

按 Ctrl+C 终止。

---

## Task 4: 前端 in-place（先断 import）

**Files:**
- Modify: `frontend/src/router/routes.tsx`
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/layout/base/nav.tsx`
- Modify: `frontend/src/layout/base/nav.scss`

- [ ] **Step 1：修改 `routes.tsx`**

删除：
- import: `import NewsPage from '@/pages/news'`
- import: `import BiddingPage from '@/pages/bidding'`
- 路由项：`/news`、`/bidding` 两个对象

- [ ] **Step 2：修改 `api/index.ts`**

删除最后一行 `export * as news from './news'`。

最终：

```ts
export * as session from './session'
export * as auth from './auth'
export * as memory from './memory'
export * as database from './database'
```

- [ ] **Step 3：修改 `layout/base/nav.tsx`**

删除：
- import: `IconNews`, `IconBid`（注意 `IconBid` 实际 import 名要在文件里确认）
- import: `import { industryState } from '@/store/industry'`、`useSnapshot`、`useMemo`、`Dropdown`、`DownOutlined`（如果只被 industry-selector 用）
- 顶部 `currentIndustryId` / `industries` 解构 + `currentIndustry` `useMemo`（约 line 24-30）
- menu items 数组里 `key: 'news'` 和 `key: 'bid'` 两个对象（约 line 88-99）
- 整个 `industry-selector` Dropdown JSX（约 line 113-145）
- `industryMenuItems` `useMemo`（约 line 32-???，如果只被 industry-selector 用）

- [ ] **Step 4：修改 `layout/base/nav.scss`**

删除整个 `.industry-selector` 样式块。

- [ ] **Step 5：grep 确认没遗漏对 store/industry 的引用**

```bash
cd frontend
grep -rn "store/industry\|industryState\|INDUSTRY_CONFIGS\|getCurrentIndustry\|setCurrentIndustry" src/
```

Expected：只剩 `src/pages/index/index.tsx` 和 `src/pages/chat/newchat.tsx` 还引用（这两个在 Task 5/6 处理），加 `src/store/industry.ts` 自己。

---

## Task 5: 首页改造（pages/index）

**Files:**
- Modify: `frontend/src/pages/index/index.tsx`

- [ ] **Step 1：重写 `pages/index/index.tsx`**

替换为：

```tsx
import IconBg from '@/assets/index/bg.png'
import IconSearch from '@/assets/index/search.svg'
import { Input } from 'antd'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import styles from './index.module.scss'

// 研究模板卡片（通用研究方法论维度，非行业）
const RESEARCH_TEMPLATES = [
  {
    id: 'market_analysis',
    title: '市场分析',
    desc: '市场规模、增长趋势、主要参与者',
    prompt: '请帮我分析 [行业/产品] 的市场规模、增长趋势和主要参与者。',
    color: '#055588',
    bgColor: '#E7F4FF',
  },
  {
    id: 'competitive_research',
    title: '竞品研究',
    desc: '产品对比、技术差异、市场份额',
    prompt: '请对 [公司A] 和 [公司B] 做对比分析，包括产品、技术、市场份额。',
    color: '#1144BA',
    bgColor: '#EFF3FF',
  },
  {
    id: 'policy_interpretation',
    title: '政策解读',
    desc: '政策核心、影响范围、企业应对',
    prompt: '请解读 [政策名称] 的核心内容、影响范围和企业应对方向。',
    color: '#335519',
    bgColor: '#EDF7E6',
  },
  {
    id: 'tech_survey',
    title: '技术调研',
    desc: '技术现状、主流方案、演进方向',
    prompt: '请调研 [技术领域] 的发展现状、主流方案、技术演进方向。',
    color: '#B85C00',
    bgColor: '#FFF4E6',
  },
]

export default function Index() {
  const navigate = useNavigate()
  const [searchKeyword, setSearchKeyword] = useState('')

  const cardList = useMemo(
    () =>
      RESEARCH_TEMPLATES.map((t) => ({
        id: t.id,
        title: t.title,
        icon: IconSearch,
        desc: t.desc,
        color: t.color,
        bgColor: t.bgColor,
        prompt: t.prompt,
      })),
    [],
  )

  const filteredCardList = useMemo(() => {
    if (!searchKeyword.trim()) return cardList
    const keyword = searchKeyword.toLowerCase()
    return cardList.filter(
      (item) =>
        item.title.toLowerCase().includes(keyword) ||
        item.desc.toLowerCase().includes(keyword),
    )
  }, [cardList, searchKeyword])

  const handleCardClick = (prompt: string) => {
    navigate(`/chat?prompt=${encodeURIComponent(prompt)}`)
  }

  return (
    <div className={styles['index-page']}>
      <div className={styles.header}>
        <img className={styles.bg} src={IconBg} />
        <div className={styles.title}>Hi～欢迎使用 AI 深度研究助手</div>
        <div className={styles.desc}>
          多 Agent 协同 + Critic 自反思，自动产出结构化研究报告
        </div>
      </div>

      <div className={styles['search-bar']}>
        <div className={styles['switch']}>
          <div className={styles.active}>研究模板</div>
        </div>

        <div className={styles['search-bar__input']}>
          <Input
            prefix={<img src={IconSearch} />}
            placeholder="搜索研究模板"
            size="large"
            value={searchKeyword}
            onChange={(e) => setSearchKeyword(e.target.value)}
            allowClear
          />
        </div>
      </div>

      <div className={styles['card-list']}>
        {filteredCardList.length === 0 ? (
          <div style={{ padding: '40px', textAlign: 'center', color: '#999', width: '100%' }}>
            未找到匹配的研究模板
          </div>
        ) : (
          filteredCardList.map((item) => (
            <div
              className={styles['card-item']}
              key={item.id}
              style={{
                backgroundColor: item.bgColor,
                color: item.color,
                cursor: 'pointer',
              }}
              onClick={() => handleCardClick(item.prompt)}
            >
              <div
                className={styles['card-item__icon']}
                style={{ borderColor: item.color }}
              >
                <img src={item.icon} />
              </div>
              <div className={styles['card-item__title']}>{item.title}</div>
              <div className={styles['card-item__desc']}>{item.desc}</div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
```

> 注意：现有 `.index-page` SCSS（4 列响应式卡片布局）完全复用，无需改 `index.module.scss`。

- [ ] **Step 2：grep 确认 index 页已不再引用 industry**

```bash
grep -n "industry\|INDUSTRY" frontend/src/pages/index/index.tsx
```

Expected：无任何匹配。

---

## Task 6: 聊天页简化（pages/chat/newchat）

**Files:**
- Modify: `frontend/src/pages/chat/newchat.tsx`

- [ ] **Step 1：删除以下内容**

- `import { industryState } from '@/store/industry'`
- `import type { NewsItem, BiddingItem } from '@/api/news'`
- `import IconNews from '@/assets/layout/news.svg'`
- `import { uniqueId } from 'lodash-es'`、`import dayjs from 'dayjs'`（如果只被 sidebar 用）
- `const industry = useSnapshot(industryState)` 及 `currentIndustryName` `useMemo`
- 整个 sidebar 数据加载 `useEffect`（约 line 60-132，含 `Promise.all([api.news.getNewsList, api.news.getBiddingList])`）
- 整个 sidebar JSX（`<div className={styles['newchat-page__news-list']}>` 块，约 line 313-345）

- [ ] **Step 2：把 `recommendQuestions` 改成静态 3 条**

```tsx
const recommendQuestions = useMemo(() => [
  'AI 大模型 2024 市场规模与主要厂商',
  '新能源汽车产业链格局与上下游分析',
  '半导体国产化进展与关键卡点',
], [])
```

- [ ] **Step 3：确认 URL `?prompt=` 参数被处理**

newchat 应支持 `/chat?prompt=xxx` 直接预填 ComSender。检查现有代码：如果 `useQuery` 已读了 `title` 参数预填，新增 `prompt` 同样处理。如果没有，加一个 `useEffect`：

```tsx
useEffect(() => {
  const prompt = query.get?.('prompt')
  if (prompt) {
    // 预填到 ComSender 的逻辑，按现有 sender state 接口适配
  }
}, [])
```

> 实施时按 ComSender 的实际 props 接口调整（`defaultValue` 或 `setValue`）。

- [ ] **Step 4：grep 确认无残留**

```bash
grep -n "industry\|INDUSTRY\|getBiddingList\|getNewsList" frontend/src/pages/chat/newchat.tsx
```

Expected：无任何匹配。

---

## Task 7: 前端文件删除

- [ ] **Step 1：删除 7 处文件/目录**

```bash
cd frontend
rm -rf src/pages/news
rm -rf src/pages/bidding
rm src/pages/chat/component/news.tsx src/pages/chat/component/news.module.scss
rm src/store/industry.ts
rm src/api/news.ts
rm -rf src/components/collection-modal
rm src/configs/data/news.ts
```

- [ ] **Step 2：确认删除**

```bash
ls src/pages/news src/pages/bidding src/store/industry.ts src/api/news.ts 2>&1 | grep -i "no such"
```

Expected：每条都报 "No such file"。

- [ ] **Step 3：grep 全局确认无残留引用**

```bash
cd frontend
grep -rn "pages/news\|pages/bidding\|store/industry\|api/news\|components/collection-modal\|configs/data/news\|chat/component/news" src/ --include="*.ts" --include="*.tsx" --include="*.scss"
```

Expected：无任何匹配（如有，回到 Task 4-6 补改）。

---

## Task 8: 前端启动验证 + TypeScript check

- [ ] **Step 1：TypeScript 类型检查**

```bash
cd frontend
npx tsc --noEmit
```

Expected：无错误退出（exit code 0）。如果报错，按 stack trace 修。

- [ ] **Step 2：启动 dev server**

```bash
npm run dev
```

Expected：
- 看到 `VITE ready in ... ms`
- 无 build error

- [ ] **Step 3：浏览器访问验证**

打开 `http://localhost:5173`（或实际端口）：
- [ ] 首页：看到 4 个研究模板卡片（市场分析 / 竞品研究 / 政策解读 / 技术调研）
- [ ] 左侧导航：只有 首页/聊天/历史/记忆/知识库/数据库（**6 项**），无 "行业资讯" / "招投标信息"
- [ ] 顶部：**无**行业切换 Dropdown
- [ ] 访问 `/news`：404
- [ ] 访问 `/bidding`：404
- [ ] 点首页"市场分析"卡片：跳转 `/chat?prompt=请帮我分析...`，输入框预填
- [ ] 进 `/chat`：无 sidebar，3 条静态推荐问题（AI 大模型 / 新能源 / 半导体），输入框正常

---

## Task 9: 配置清理

**Files:**
- Modify: `backend/.env.example`
- Modify: `backend/app/requirements.txt`

- [ ] **Step 1：清理 `.env.example`**

删除：
```
# ==================== 招投标 API ====================
# 阿里云市场 - 招投标信息 API（可选）
# 申请地址: https://market.aliyun.com/detail/cmapi00063550
BID_APP_KEY=your-bid-app-key
BID_APP_SECRET=your-bid-app-secret
BID_APP_CODE=your-bid-app-code
```

> **保留** `JUHE_STOCK_API_KEY` —— `backend/app/service/stock_service.py` 仍在用。

- [ ] **Step 2：清理 `backend/app/requirements.txt`**

确认 `apscheduler` 只被已删的 `scheduler_service.py` 使用：

```bash
grep -rn "apscheduler\|APScheduler\|AsyncIOScheduler\|CronTrigger" backend/app/
```

Expected：无匹配（已删干净）。

然后从 `backend/app/requirements.txt` 删除 `apscheduler` 行。

- [ ] **Step 3：重启后端确认无依赖问题**

```bash
cd backend/app
python app_main.py
```

Expected：启动正常。Ctrl+C 终止。

---

## Task 10: DB drop

- [ ] **Step 1：连进 Postgres**

```bash
docker exec -it industry-research-assistant-postgres-1 psql -U postgres -d industry_assistant
```

- [ ] **Step 2：drop 3 张表**

```sql
DROP TABLE IF EXISTS industry_news CASCADE;
DROP TABLE IF EXISTS bidding_info CASCADE;
DROP TABLE IF EXISTS news_collection_tasks CASCADE;
```

Expected：每条返回 `DROP TABLE`。

- [ ] **Step 3：验证表已删，核心表都在**

```sql
\dt
```

Expected：
- **看不到** `industry_news` / `bidding_info` / `news_collection_tasks`
- **看到** `users` / `chat_sessions` / `chat_messages` / `chat_attachments` / `long_term_memories` / `knowledge_bases` / `documents` / `industry_stats` / `company_data` / `policy_data` / `research_checkpoints`

- [ ] **Step 4：退出 psql**

```sql
\q
```

---

## Task 11: 端到端 smoke 验证

- [ ] **Step 1：启动后端 + 前端**

```bash
# Terminal 1
cd backend/app && python app_main.py

# Terminal 2
cd frontend && npm run dev
```

Expected：两个都起得来。

- [ ] **Step 2：浏览器跑一次完整 deep research**

打开 `/chat`，输入：

```
新能源汽车 2024 年市场现状
```

观察：
- [ ] Plan / Scout / Analyze / Wizard / Write / Review 各阶段 SSE 流式事件正常
- [ ] 最终生成 6,000+ 字研究报告
- [ ] Wall time 与之前 `parallel-002`（1590s / 26 min）相当，无显著回归

- [ ] **Step 3（可选）：跑 eval smoke 复测**

```bash
cd backend
python -m app.eval.cli smoke --case parallel-002
```

Expected：
- 7 维 evaluator 分数与 `2026-05-27-smoke-20260527-032820-6f46ac` 相当
- coherence ≥ 7.5（关键护栏）
- relevance ≥ 8.0
- Wall < 2000s

---

## Task 12: 提交（3 个 commits）

按变更性质分 3 个 commit 便于 review：

- [ ] **Commit 1: 后端清理**

```bash
git add backend/app/app_main.py \
        backend/app/models/__init__.py \
        backend/.env.example \
        backend/app/requirements.txt \
        backend/backup/2026-05-27-news-bidding-tables.sql
git add -u backend/app/router/news_router.py \
            backend/app/service/news_collection_service.py \
            backend/app/service/bidding_service.py \
            backend/app/service/scheduler_service.py \
            backend/app/config/industry_config.py \
            backend/app/models/news.py
git commit -m "refactor(backend): 删除行业资讯/招投标/定时采集，改造为通用研究助手

- 删除 news_router / news_collection_service / bidding_service
- 删除 scheduler_service（APScheduler 每日采集任务）
- 删除 industry_config（4 行业关键词预设）
- 删除 models.news（IndustryNews/BiddingInfo/NewsCollectionTask）
- app_main.py: 移除 scheduler 启动/关闭 + news_router 注册
- .env.example: 删除 BID_APP_* 三件套
- requirements.txt: 删除 apscheduler
- 备份脚本：backend/backup/2026-05-27-news-bidding-tables.sql

Spec: docs/superpowers/specs/2026-05-27-generalize-to-research-assistant-design.md
Plan: docs/superpowers/plans/2026-05-27-generalize-to-research-assistant-implementation.md"
```

- [ ] **Commit 2: 前端清理 + 首页/聊天页改造**

```bash
git add frontend/src/router/routes.tsx \
        frontend/src/api/index.ts \
        frontend/src/layout/base/nav.tsx \
        frontend/src/layout/base/nav.scss \
        frontend/src/pages/index/index.tsx \
        frontend/src/pages/chat/newchat.tsx
git add -u frontend/src/pages/news/ \
            frontend/src/pages/bidding/ \
            frontend/src/pages/chat/component/news.tsx \
            frontend/src/pages/chat/component/news.module.scss \
            frontend/src/store/industry.ts \
            frontend/src/api/news.ts \
            frontend/src/components/collection-modal/ \
            frontend/src/configs/data/news.ts
git commit -m "refactor(frontend): 删除行业切换器和资讯/招投标页，首页改造为研究模板

- 删除 pages/news + pages/bidding 整页
- 删除 store/industry（全局行业 store）+ api/news（API client）
- 删除 components/collection-modal + configs/data/news
- 删除 chat/component/news.tsx（sidebar mock 新闻）
- nav.tsx: 移除 industry-selector Dropdown 和 news/bid 菜单项
- pages/index: 4 个行业卡片 → 4 个研究模板卡片（市场分析/竞品研究/政策解读/技术调研）
- pages/chat/newchat: 移除 sidebar API 拉取，推荐问题改静态 3 条
- 路由 /news /bidding 404"
```

- [ ] **Commit 3: 文档 + spec/plan**

```bash
git add docs/superpowers/specs/2026-05-27-generalize-to-research-assistant-design.md \
        docs/superpowers/plans/2026-05-27-generalize-to-research-assistant-implementation.md
git commit -m "docs(superpowers): generalize-to-research-assistant spec + plan"
```

- [ ] **Step 4：确认提交 log**

```bash
git log --oneline -5
```

Expected：3 个新 commits 加之前的 head（共 4+ 条）。

---

## 验证清单（全部 Task 完成后逐项过）

| # | 项 | 命令 / 步骤 | 期望 |
|---|---|---|---|
| V1 | 后端 boot | `python backend/app/app_main.py` | 无 ImportError，无 scheduler 启动日志 |
| V2 | 前端 boot | `cd frontend && npm run dev` | VITE ready，无 TS 报错 |
| V3 | 路由 404 | `curl -i /news`, `/bidding` | 404 |
| V4 | 菜单 | UI 左侧 | 6 项菜单，无行业 Dropdown |
| V5 | 首页 | UI `/` | 4 研究模板卡片，点击跳 `/chat?prompt=...` |
| V6 | 聊天页 | UI `/chat` | 无 sidebar，3 静态推荐 |
| V7 | E2E | 输入"新能源汽车 2024 市场现状" | 6000+ 字报告生成 |
| V8 | DB | `\dt` | news 3 表消失，其他都在 |
| V9 | grep 残留 | 见 Task 4 Step 5 / Task 7 Step 3 | 无残留 |

---

## 风险与回滚

| 风险 | 对策 |
|---|---|
| 误删 BOCHA / JUHE 配置 | Task 9 明确**保留** `BOCHA_API_KEY` / `JUHE_STOCK_API_KEY` |
| 误删 `industry_data` 模型 | `industry_data.py` 与 `news.py` 是不同文件，只删后者 |
| 引用残留导致启动失败 | 每个 Task 末尾有 grep 验证步骤 |
| DB drop 后想恢复 | Task 0 已 pg_dump 备份到 `backup/2026-05-27-...sql` |

**回滚**：
- 代码：`git revert <commit1>..<commit3>`
- DB：`docker exec ... psql -U postgres -d industry_assistant < backend/backup/2026-05-27-news-bidding-tables.sql`

---

## Self-Review 检查（plan 作者自检）

- ✅ Spec 覆盖：spec §3 全部 6 个删除组（A-F）都有对应 Task
- ✅ 无 placeholder：所有 Task 都有具体文件路径 + 具体命令
- ✅ Type 一致性：保留模型列表（IndustryStats/CompanyData/PolicyData/ResearchCheckpoint）在 Task 1 / Task 10 验证步骤里一致
- ✅ 风险点（stock_service 还用 JUHE_STOCK_API_KEY）已在 §"不动" + Task 9 Step 1 显式标注
- ✅ 删除顺序：所有引用方先 in-place 改完再删文件（避免中间状态 broken import）
