# 前端视觉改版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把前端「改得面目全非」——现代简约科技风（钴蓝主色）换肤 + 外壳布局重构 + 首页重写，并隐藏 记忆库/知识库/数据库 三个入口；聊天页与右侧详情面板只换肤不改结构。

**Architecture:** 以「全局 Design Token + Antd `colorPrimary` cssVar」为换肤主杠杆——大部分页面（含聊天页）的强调色都走 `var(--ant-color-primary)`，因此改 token 即可全站传播。外壳（`layout/base`）与首页（`pages/index`）按已批准的高保真稿重写。导航/路由删除三项入口、保留页面源码。

**Tech Stack:** React 19 + Ant Design 5 (`ConfigProvider` cssVar) + React Router 6 + Vite + SCSS Module。自托管字体「得意黑 Smiley Sans」。

**验证方式说明（重要）：** 该项目 `package.json` 无测试运行器，前端为视觉改版，故本计划**不写单元测试**；每个任务的验证 = `npm run build` 通过 + `npm run lint` 通过 +（关键任务）`npm run dev` 人工目测。所有命令在 `frontend/` 目录下执行。

**规格来源：** `docs/superpowers/specs/2026-06-09-frontend-redesign-design.md`

---

## 文件结构总览

- `frontend/src/index.css` — 全局 Design Token（CSS 变量）、`@font-face`、全局字体/背景。
- `frontend/src/assets/fonts/SmileySans-Oblique.woff2` — 自托管展示字体（新增）。
- `frontend/src/App.tsx` — Antd `ConfigProvider` 主题 token（主色/圆角/字体）。
- `frontend/src/layout/base/{index.scss,index.tsx,nav.tsx,nav.scss,nav-item.tsx,nav-item.scss,footer.tsx,footer.scss}` — 外壳重构为 208px 宽文字侧栏 + 品牌区 + 账户区。
- `frontend/src/router/routes.tsx` — 删除 `/knowledge` `/memory` `/database` 路由与 import。
- `frontend/src/pages/index/{index.tsx,index.module.scss}` — 首页重写。
- 聊天/公共组件 SCSS — 仅在 token 传播未覆盖处做定点替换。

---

## Task 1: 新建分支

**Files:** 无（git 操作）

- [ ] **Step 1: 从 main 切出前端改版分支**

```bash
git checkout main
git pull
git checkout -b feat/frontend-redesign
```

> 说明：当前工作分支 `feat/raw-sources-data-analyst-refactor` 与本次前端改版无关，须独立分支。若 `main` 上没有本计划/spec 文件，先把 `docs/superpowers/specs/2026-06-09-frontend-redesign-design.md` 与本计划文件 `git add` 进来一并提交。

- [ ] **Step 2: 提交设计文档与计划**

```bash
git add docs/superpowers/specs/2026-06-09-frontend-redesign-design.md docs/superpowers/plans/2026-06-10-frontend-redesign.md
git commit -m "docs: 前端视觉改版设计文档与实现计划"
```

---

## Task 2: 自托管展示字体「得意黑」

**Files:**
- Create: `frontend/src/assets/fonts/SmileySans-Oblique.woff2`

- [ ] **Step 1: 下载字体 woff2**

从官方发布页下载得意黑（Smiley Sans）的 woff2 字重文件：
- 发布页：`https://github.com/atelier-anchor/smiley-sans/releases`（取最新 release 的 zip，内含 `SmileySans-Oblique.ttf.woff2`）

将其中的 `*.woff2` 重命名为 `SmileySans-Oblique.woff2`，放到 `frontend/src/assets/fonts/`。

```bash
mkdir -p frontend/src/assets/fonts
# 把下载解压得到的 woff2 拷贝/重命名到目标路径：
# frontend/src/assets/fonts/SmileySans-Oblique.woff2
```

- [ ] **Step 2: 验证文件存在且非空**

```bash
ls -l frontend/src/assets/fonts/SmileySans-Oblique.woff2
```
Expected: 文件存在，体积约几百 KB（非 0 字节）。

> `@font-face` 声明在 Task 3 的 `index.css` 中统一写入（与 token 同处，便于维护）。

---

## Task 3: 全局 Design Token、字体与背景（`index.css`）

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: 用新内容替换 `index.css`**

将整个文件替换为：

```css
@font-face {
  font-family: 'Smiley Sans';
  src: url('./assets/fonts/SmileySans-Oblique.woff2') format('woff2');
  font-weight: 400 700;
  font-style: normal;
  font-display: swap;
}

:root {
  /* 主色 */
  --acc: #2563eb;
  --acc-2: #3b82f6;
  --acc-grad: linear-gradient(135deg, #2563eb, #3b82f6);
  --acc-soft: #eef3ff;

  /* 中性层次 */
  --bg: #f6f7fb;
  --surface: #ffffff;
  --border: #eef0f6;
  --text-1: #15172b;
  --text-2: #646a82;
  --text-3: #a9adc0;

  /* 语义色（研究模板卡） */
  --ok: #1f9d57;
  --warn: #d97706;
  --magenta: #db2777;

  /* 圆角 / 阴影 */
  --radius-card: 14px;
  --radius-ctl: 11px;
  --shadow-sm: 0 8px 24px rgba(40, 42, 80, 0.06);
  --shadow-md: 0 12px 28px rgba(40, 42, 80, 0.1);

  /* 字体 */
  --font-sans: -apple-system, BlinkMacSystemFont, 'PingFang SC',
    'Microsoft YaHei', 'Segoe UI', sans-serif;
  --font-display: 'Smiley Sans', var(--font-sans);
  --font-mono: 'Space Mono', ui-monospace, SFMono-Regular, Menlo, monospace;

  background-color: var(--bg);
  color: var(--text-1);
  font-size: 14px;
  line-height: 1.5;
  font-family: var(--font-sans);

  font-synthesis: none;
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

.scrollbar-style {
  scrollbar-width: thin;
}
.scrollbar-style::-webkit-scrollbar {
  width: 8px;
}
```

- [ ] **Step 2: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功，无报错（字体路径能被 Vite 解析）。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/index.css frontend/src/assets/fonts/SmileySans-Oblique.woff2
git commit -m "feat(前端): 引入钴蓝设计 Token 与得意黑展示字体"
```

---

## Task 4: Antd 主题 token（`App.tsx`）

**Files:**
- Modify: `frontend/src/App.tsx:10-19`

- [ ] **Step 1: 更新 `ConfigProvider` theme**

把现有的 `theme={{...}}`：

```tsx
      theme={{
        cssVar: true,
        token: {
          colorPrimary: '#2861E7',
          borderRadius: 6
        },
      }}
```

替换为：

```tsx
      theme={{
        cssVar: true,
        token: {
          colorPrimary: '#2563EB',
          borderRadius: 10,
          fontFamily:
            "-apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', 'Segoe UI', sans-serif",
        },
      }}
```

- [ ] **Step 2: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功。`--ant-color-primary` 全站变为钴蓝。

- [ ] **Step 3: 提交**

```bash
git add frontend/src/App.tsx
git commit -m "feat(前端): Antd 主色切为钴蓝并统一字体/圆角"
```

---

## Task 5: 外壳布局——侧栏容器与品牌/账户区骨架（`layout/base/index.scss` + `index.tsx`）

**Files:**
- Modify: `frontend/src/layout/base/index.scss`
- Modify: `frontend/src/layout/base/index.tsx`

- [ ] **Step 1: 重写 `index.scss`（侧栏宽度 94→208，配色用 token）**

```scss
.base-layout {
  padding-left: 208px;
}

.base-layout__sidebar {
  position: fixed;
  z-index: 1000;
  left: 0;
  top: 0;
  bottom: 0;
  width: 208px;
  background-color: var(--surface);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;

  .base-layout__sidebar-main {
    flex-grow: 1;
    overflow: auto;
    display: flex;
    flex-direction: column;
    padding: 20px 16px;
  }
}

.base-layout__content {
  min-height: 100vh;
  flex-shrink: 0;
  background-color: var(--bg);
}
```

- [ ] **Step 2: 在 `index.tsx` 顶部加品牌区**

把现有 return 改为（在 `<Nav />` 上方插入品牌块）：

```tsx
export function BaseLayout({ children }: { children?: React.ReactNode }) {
  return (
    <div className="base-layout">
      <div className="base-layout__sidebar">
        <div className="base-layout__sidebar-main scrollbar-style">
          <div className="base-layout__brand">
            <div className="base-layout__brand-logo" />
            <span className="base-layout__brand-name">深度研究助手</span>
          </div>

          <Nav />

          <Footer />
        </div>
      </div>

      <div className="base-layout__content">{children}</div>
    </div>
  )
}
```

- [ ] **Step 3: 在 `index.scss` 追加品牌区样式**

在文件末尾追加：

```scss
.base-layout__brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 8px 20px;

  .base-layout__brand-logo {
    width: 32px;
    height: 32px;
    border-radius: 9px;
    background: var(--acc-grad);
    box-shadow: 0 4px 12px rgba(37, 99, 235, 0.4);
    flex-shrink: 0;
  }

  .base-layout__brand-name {
    font-size: 15px;
    font-weight: 700;
    color: var(--text-1);
    letter-spacing: -0.01em;
  }
}
```

- [ ] **Step 4: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功。

> 提交与 Task 6/7 合并（外壳是一个整体），见 Task 7 Step 末。

---

## Task 6: 导航项重构为「图标+文字」横向条目（`nav-item.scss`）

**Files:**
- Modify: `frontend/src/layout/base/nav-item.scss`

> `nav-item.tsx` 现有结构（`<img icon>` + `<span label>`）无需改动，仅重写样式：从竖直 64×64 图标块改为横向标签条目；active 用实心钴蓝 + 反色图标（沿用现有 `filter: brightness(0) invert(1)` 机制，适配 SVG 资源）。

- [ ] **Step 1: 重写 `nav-item.scss`**

```scss
.base-layout-nav__item {
  display: flex;
  align-items: center;
  gap: 11px;
  height: 44px;
  width: 100%;
  padding: 0 12px;
  border-radius: var(--radius-ctl);
  color: var(--text-2);
  font-size: 14px;
  font-weight: 500;
  transition: all 0.2s;
  position: relative;

  &:hover {
    background-color: #f5f6fb;
    color: var(--text-1);
  }

  &.active {
    background-color: var(--acc);
    color: #fff;

    .base-layout-nav__item-icon {
      filter: brightness(0) invert(1);
    }
  }

  .base-layout-nav__item-icon {
    display: block;
    width: 18px;
    height: 18px;
    flex-shrink: 0;
  }

  .base-layout-nav__item-label {
    font-size: 14px;
  }

  .base-layout-nav__item-dot {
    display: block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background-color: red;
    position: absolute;
    top: 50%;
    right: 12px;
    transform: translateY(-50%);
  }
}
```

- [ ] **Step 2: 构建验证**

Run: `cd frontend && npm run build`
Expected: 构建成功。

---

## Task 7: 导航精简 + 账户区（`nav.tsx` / `nav.scss` / `footer.tsx` / `footer.scss`）

**Files:**
- Modify: `frontend/src/layout/base/nav.tsx`
- Modify: `frontend/src/layout/base/nav.scss`
- Modify: `frontend/src/layout/base/footer.tsx`
- Modify: `frontend/src/layout/base/footer.scss`

- [ ] **Step 1: 重写 `nav.tsx`——移除 记忆库/知识库/数据库 三项及其图标 import**

```tsx
import IconHistory from '@/assets/layout/history.svg'
import IconHome from '@/assets/layout/home.svg'
import IconNewChat from '@/assets/layout/newchat.svg'
import { SessionDrawer } from '@/components/session-drawer'
import { useMemo, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { NavItem } from './nav-item'
import './nav.scss'

export function Nav() {
  const { pathname } = useLocation()
  const [sessionDrawerOpen, setSessionDrawerOpen] = useState(false)

  const items = useMemo(
    () => [
      {
        key: 'home',
        label: '首页',
        icon: IconHome,
        href: '/',
      },
      {
        key: 'newchat',
        label: '新的聊天',
        icon: IconNewChat,
        href: '/chat',
      },
      {
        key: 'history',
        label: '对话历史',
        icon: IconHistory,
        href: '#',
        onClick: () => setSessionDrawerOpen(true),
      },
    ],
    [],
  )

  return (
    <>
      <div className="base-layout-nav">
        <div className="base-layout-nav__label">导航</div>
        {items.map(({ key, onClick, ...item }) => (
          <NavItem
            key={key}
            {...item}
            active={pathname === item.href}
            onClick={onClick}
          />
        ))}
      </div>
      <SessionDrawer
        open={sessionDrawerOpen}
        onClose={() => setSessionDrawerOpen(false)}
      />
    </>
  )
}
```

- [ ] **Step 2: 重写 `nav.scss`（竖直堆叠 + 分组标签）**

```scss
.base-layout-nav {
  flex-grow: 1;
  flex-shrink: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 3px;

  .base-layout-nav__label {
    font-size: 10px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--text-3);
    padding: 6px 8px 10px;
  }
}
```

- [ ] **Step 3: 重写 `footer.tsx` 的 return——账户横条（头像 + 用户名 + 副标题）**

把现有 return（`<div className="base-layout-footer">...</div>`）替换为：

```tsx
  return (
    <div className="base-layout-footer">
      <Dropdown
        menu={{ items: menuItems }}
        placement="topRight"
        trigger={['click']}
        overlayClassName="user-dropdown-overlay"
      >
        <div className="account-row">
          <Avatar size={32} icon={<UserOutlined />} className="user-avatar">
            {getAvatarText()}
          </Avatar>
          <div className="account-row__meta">
            <div className="account-row__name">{user?.username || '用户'}</div>
            <div className="account-row__sub">个人工作区</div>
          </div>
        </div>
      </Dropdown>
    </div>
  )
```

- [ ] **Step 4: 重写 `footer.scss` 的容器与头像部分**

把文件顶部到 `.user-avatar-wrapper { ... }` 这段（第 3–28 行）替换为：

```scss
.base-layout-footer {
  flex-shrink: 0;
  margin-top: auto;
  padding-top: 12px;
}

.account-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border-radius: var(--radius-ctl);
  background: var(--bg);
  cursor: pointer;
  transition: background 0.15s ease;

  &:hover {
    background: #eef0f6;
  }

  .user-avatar {
    background: linear-gradient(135deg, #fbbf24, #f472b6);
    color: #fff;
    font-weight: 500;
    border: none;
    flex-shrink: 0;
  }

  &__meta {
    min-width: 0;
  }

  &__name {
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-1);
    line-height: 1.2;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  &__sub {
    font-size: 10px;
    color: var(--text-3);
  }
}
```

> 文件其余部分（`:global { .user-dropdown-overlay ... }` 与 `.user-menu-info`）保持不变。

- [ ] **Step 5: 构建 + 目测验证整套外壳**

Run: `cd frontend && npm run build && npm run lint`
Expected: 均通过。

Run: `cd frontend && npm run dev`，浏览器目测侧栏：208px 宽、品牌区、3 个文字导航项（首页/新的聊天/对话历史）、当前项钴蓝高亮、底部账户横条。确认 记忆库/知识库/数据库 已消失。

- [ ] **Step 6: 提交外壳**

```bash
git add frontend/src/layout/base
git commit -m "feat(前端): 侧栏重构为208px宽文字导航并隐藏记忆/知识/数据库入口"
```

---

## Task 8: 删除被隐藏页面的路由（`routes.tsx`）

**Files:**
- Modify: `frontend/src/router/routes.tsx`

- [ ] **Step 1: 移除三条路由与对应 import**

删除这三行 import：

```tsx
import KnowledgePage from '@/pages/knowledge'
import MemoryPage from '@/pages/memory'
import DatabasePage from '@/pages/database'
```

并从 `routes` 数组中删除这三段：

```tsx
  {
    path: '/knowledge',
    Component: KnowledgePage,
  },
  {
    path: '/memory',
    Component: MemoryPage,
  },
  {
    path: '/database',
    Component: DatabasePage,
  },
```

> 保留 `pages/knowledge`、`pages/memory`、`pages/database` 源码文件不删。

- [ ] **Step 2: 构建 + lint 验证（确保无未用 import 报错）**

Run: `cd frontend && npm run build && npm run lint`
Expected: 通过；无 "unused import" 或 "Cannot find" 报错。

- [ ] **Step 3: 目测验证路由落 404**

`npm run dev` 后浏览器访问 `/knowledge`、`/memory`、`/database`，应重定向到 `/404`。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/router/routes.tsx
git commit -m "feat(前端): 移除记忆/知识/数据库路由，访问落404"
```

---

## Task 9: 首页重写（`pages/index`）

**Files:**
- Modify: `frontend/src/pages/index/index.tsx`
- Modify: `frontend/src/pages/index/index.module.scss`

> 业务逻辑不变：保留 `RESEARCH_TEMPLATES`、`searchKeyword` 实时过滤、点击卡片 `navigate('/chat?prompt=...')`。搜索框保持「过滤模板」语义，不新增「自由文本进聊天」行为（已在 spec 标为后续增强）。模板卡为 2 列网格（4 张 = 2 行）。

- [ ] **Step 1: 重写 `index.tsx`**

```tsx
import IconSearch from '@/assets/index/search.svg'
import { Input } from 'antd'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import styles from './index.module.scss'

// 研究模板：按研究方法论维度（市场 / 竞品 / 政策 / 技术），与具体行业解耦
const RESEARCH_TEMPLATES = [
  {
    id: 'market_analysis',
    title: '市场分析',
    desc: '市场规模、增长趋势、主要参与者',
    prompt: '请帮我分析 [行业/产品] 的市场规模、增长趋势和主要参与者。',
    emoji: '📈',
    tone: 'var(--acc)',
    soft: '#eef3ff',
  },
  {
    id: 'competitive_research',
    title: '竞品研究',
    desc: '产品对比、技术差异、市场份额',
    prompt: '请对 [公司A] 和 [公司B] 做对比分析，包括产品、技术、市场份额。',
    emoji: '⚔️',
    tone: 'var(--ok)',
    soft: '#eafaf0',
  },
  {
    id: 'policy_interpretation',
    title: '政策解读',
    desc: '政策核心、影响范围、企业应对',
    prompt: '请解读 [政策名称] 的核心内容、影响范围和企业应对方向。',
    emoji: '📜',
    tone: 'var(--warn)',
    soft: '#fff2e6',
  },
  {
    id: 'tech_survey',
    title: '技术调研',
    desc: '技术现状、主流方案、演进方向',
    prompt: '请调研 [技术领域] 的发展现状、主流方案、技术演进方向。',
    emoji: '🔬',
    tone: 'var(--magenta)',
    soft: '#fde8f3',
  },
]

export default function Index() {
  const navigate = useNavigate()
  const [searchKeyword, setSearchKeyword] = useState('')

  const filteredCardList = useMemo(() => {
    if (!searchKeyword.trim()) return RESEARCH_TEMPLATES
    const keyword = searchKeyword.toLowerCase()
    return RESEARCH_TEMPLATES.filter(
      (item) =>
        item.title.toLowerCase().includes(keyword) ||
        item.desc.toLowerCase().includes(keyword),
    )
  }, [searchKeyword])

  const handleCardClick = (prompt: string) => {
    navigate(`/chat?prompt=${encodeURIComponent(prompt)}`)
  }

  return (
    <div className={styles['index-page']}>
      <section className={styles.hero}>
        <div className={styles.tag}>
          <i />
          多 Agent 协同 · Critic 自反思
        </div>
        <h1 className={styles.title}>
          把复杂课题，
          <br />
          <span className={styles.hl}>交给会深度推演的 AI</span>
        </h1>
        <p className={styles.subtitle}>
          全自动深度检索 + 多专家协同，自动产出高置信度、可溯源的结构化研究报告。
        </p>

        <div className={styles.search}>
          <Input
            prefix={<img src={IconSearch} />}
            placeholder="搜索研究模板"
            size="large"
            variant="borderless"
            value={searchKeyword}
            onChange={(e) => setSearchKeyword(e.target.value)}
            allowClear
          />
        </div>
      </section>

      <section className={styles.section}>
        <div className={styles.sectionHead}>
          <h3>研究模板</h3>
        </div>

        <div className={styles.grid}>
          {filteredCardList.length === 0 ? (
            <div className={styles.empty}>未找到匹配的研究模板</div>
          ) : (
            filteredCardList.map((item) => (
              <div
                className={styles.tpl}
                key={item.id}
                onClick={() => handleCardClick(item.prompt)}
              >
                <div
                  className={styles.tplIcon}
                  style={{ background: item.soft, color: item.tone }}
                >
                  {item.emoji}
                </div>
                <div className={styles.tplTitle}>{item.title}</div>
                <div className={styles.tplDesc}>{item.desc}</div>
                <span className={styles.tplArrow}>↗</span>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  )
}
```

- [ ] **Step 2: 重写 `index.module.scss`**

```scss
.index-page {
  margin: 0 auto;
  min-height: 100%;
  max-width: 980px;
  box-sizing: border-box;
  padding: 0 44px 48px;
}

.hero {
  position: relative;
  overflow: hidden;
  padding: 56px 0 36px;

  &::before {
    content: '';
    position: absolute;
    inset: 0;
    background-image: linear-gradient(var(--border) 1px, transparent 1px),
      linear-gradient(90deg, var(--border) 1px, transparent 1px);
    background-size: 26px 26px;
    -webkit-mask-image: radial-gradient(70% 70% at 80% 0%, #000, transparent);
    mask-image: radial-gradient(70% 70% at 80% 0%, #000, transparent);
    opacity: 0.6;
    pointer-events: none;
  }

  > * {
    position: relative;
  }
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--acc);
  background: var(--acc-soft);
  border: 1px solid rgba(37, 99, 235, 0.22);
  padding: 4px 11px;
  border-radius: 99px;
  margin-bottom: 18px;

  i {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--acc);
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.22);
  }
}

.title {
  font-family: var(--font-display);
  font-size: 38px;
  line-height: 1.15;
  font-weight: 700;
  letter-spacing: 0.01em;
  color: var(--text-1);
  margin: 0 0 14px;

  .hl {
    background: var(--acc-grad);
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
  }
}

.subtitle {
  font-size: 14px;
  color: var(--text-2);
  max-width: 460px;
  line-height: 1.6;
  margin: 0 0 24px;
}

.search {
  display: flex;
  align-items: center;
  max-width: 520px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 13px;
  padding: 4px 12px;
  box-shadow: var(--shadow-sm);

  img {
    width: 20px;
    height: 20px;
  }
}

.section {
  margin-top: 36px;
}

.sectionHead {
  margin-bottom: 16px;

  h3 {
    font-size: 16px;
    font-weight: 700;
    color: var(--text-1);
    margin: 0;
    letter-spacing: -0.01em;
  }
}

.grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;

  @media (max-width: 720px) {
    grid-template-columns: 1fr;
  }
}

.empty {
  grid-column: 1 / -1;
  padding: 40px;
  text-align: center;
  color: var(--text-3);
}

.tpl {
  position: relative;
  overflow: hidden;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-card);
  padding: 20px;
  cursor: pointer;
  transition: all 0.2s;

  &:hover {
    transform: translateY(-2px);
    box-shadow: var(--shadow-md);
    border-color: #e0e3f0;
  }
}

.tplIcon {
  width: 40px;
  height: 40px;
  border-radius: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  margin-bottom: 14px;
}

.tplTitle {
  font-size: 15px;
  font-weight: 700;
  color: var(--text-1);
  margin-bottom: 5px;
}

.tplDesc {
  font-size: 12px;
  color: var(--text-2);
  line-height: 1.5;
}

.tplArrow {
  position: absolute;
  top: 18px;
  right: 18px;
  color: #cfd3e2;
  font-size: 15px;
}
```

- [ ] **Step 3: 检查未用资源 import**

`index.tsx` 不再使用 `IconBg`（原 `@/assets/index/bg.png`）。确认已不在文件中引用（上面的新版未 import 它）。`bg.png` 文件保留在 assets，不删。

- [ ] **Step 4: 构建 + lint 验证**

Run: `cd frontend && npm run build && npm run lint`
Expected: 通过，无未用变量报错。

- [ ] **Step 5: 目测验证**

`npm run dev` 看首页：Hero（标签+渐变高亮标题+副标题+搜索框）、模板 2×2 卡片悬浮上浮、搜索过滤生效、点击卡片跳转 `/chat?prompt=...`。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/pages/index
git commit -m "feat(前端): 重写首页为现代简约科技风Hero与模板卡片"
```

---

## Task 10: 聊天页与右侧详情面板换肤校验 + 定点修补

**Files:**
- Audit/Modify（按需）: `frontend/src/pages/chat/**/*.scss`、`frontend/src/components/{session-drawer,sender}/index.scss`、`frontend/src/pages/auth/login.module.scss`

> 大部分强调色走 `var(--ant-color-primary)`，已被 Task 4 自动换为钴蓝。本任务只做「目测找出仍显旧蓝/突兀处 → 定点替换为 token」，不重构结构。

- [ ] **Step 1: 搜索遗留旧品牌蓝硬编码**

Run:
```bash
cd frontend && grep -rniE "#055588|#2861e7|#1144ba|#4a90e2|#357abd|#2861E7" src/pages/chat src/components src/pages/auth
```
Expected: 列出仍硬编码旧蓝的位置（预期很少或没有）。

- [ ] **Step 2: 逐处替换**

对 Step 1 命中的每一处：
- 若是「主强调色/链接/激活态」用途 → 替换为 `var(--ant-color-primary)`（或渐变处用 `var(--acc-grad)`）。
- 若是浅色背景底 → 替换为 `var(--acc-soft)`。
- 纯中性灰（如 `#999`、`#f4f4f4`）保持不动。

- [ ] **Step 3: 目测聊天全流程**

`npm run dev`：从首页点模板进入 `/chat`，跑一轮研究，逐个查看：聊天消息区、`research-process`、右侧 `research-detail` / `step-detail-panel`、`session-drawer`、`sender` 输入框、登录页。确认主色统一为钴蓝、字体为新栈、无明显旧蓝残留；布局结构未变。

- [ ] **Step 4: 构建 + lint**

Run: `cd frontend && npm run build && npm run lint`
Expected: 通过。

- [ ] **Step 5: 提交**

```bash
git add frontend/src/pages/chat frontend/src/components frontend/src/pages/auth
git commit -m "feat(前端): 聊天页/详情面板/公共组件换肤对齐钴蓝主题"
```

---

## Task 11: 全量终检

**Files:** 无（验证）

- [ ] **Step 1: 全量构建与 lint**

Run: `cd frontend && npm run build && npm run lint`
Expected: 均通过。

- [ ] **Step 2: 逐页目测清单**

`npm run dev`，逐项确认：
- [ ] 侧栏 208px 宽、品牌区、3 项文字导航、钴蓝高亮、底部账户区。
- [ ] 导航无 记忆库/知识库/数据库；直接访问 `/knowledge` `/memory` `/database` 落 `/404`。
- [ ] 首页 Hero + 模板卡新样式、搜索过滤、卡片跳转正常。
- [ ] 聊天页 + 右侧详情面板布局未变、主色字体已对齐新主题。
- [ ] 登录页、404 视觉与新主题一致。
- [ ] 标题处得意黑字体已生效。

- [ ] **Step 3: 收尾提交（若终检有零星修补）**

```bash
git add -A
git commit -m "chore(前端): 改版终检与零星样式修补"
```

---

## Self-Review 结论

- **Spec 覆盖：** 基调/Token（T3,T4）、字体（T2,T3）、外壳（T5,T6,T7）、隐藏三项（T7 导航 + T8 路由）、首页（T9）、聊天换肤（T10）、公共组件统一（T10）、范围红线（各任务均不动业务逻辑）、验证（T11）。全部命中。
- **占位符：** 无 TBD/TODO；T10 的「定点替换」给出了明确的匹配命令 + old→new 映射规则 + 验证，属可执行规则而非占位。
- **命名一致：** CSS 变量（`--acc`/`--acc-soft`/`--acc-grad`/`--radius-card` 等）在 T3 定义、后续任务一致引用；`base-layout__brand*`、`account-row*`、`base-layout-nav__label` 类名前后一致。
