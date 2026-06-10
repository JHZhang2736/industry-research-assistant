# 前端视觉改版设计文档

- 日期：2026-06-09
- 范围：仅前端（`frontend/`），后端零改动
- 目标：将前端「改得面目全非」——以页面**布局重构 + 全局换肤**为主，同时隐藏「记忆库 / 知识库 / 数据库」三个入口

## 1. 背景与目标

当前前端为 React 19 + Ant Design 5 + React Router 6 + Vite + SCSS Module，浅色蓝调（`#055588` 系），左侧 94px 窄图标侧栏，导航含 首页 / 新的聊天 / 对话历史 / 记忆库 / 知识库 / 数据库。

本次改版要达成：

1. 整体视觉焕然一新，采用**现代简约科技风（打磨版）**，避免通用 AI 模板套路。
2. 应用外壳布局由窄图标侧栏改为**宽文字侧栏**。
3. 首页按新风格重构。
4. **隐藏** 记忆库 / 知识库 / 数据库 三项。
5. 聊天页与右侧详情面板**只换肤、不重构布局**。

## 2. 设计基调与 Design Token

风格：浅色、大留白、单一钴蓝强调色、有性格的字体、克制的质感细节。

落地位置：全局 CSS 变量（`src/index.css`）+ Ant Design 5 `ConfigProvider` 主题（`src/antd.scss` 及/或 App 根的 theme token），各页面 SCSS 引用变量而非硬编码色值。

### 颜色

| 用途 | 值 |
| --- | --- |
| 主色 acc | `#2563EB` |
| 主色亮 acc2 | `#3B82F6` |
| 页面底 | `#F6F7FB` |
| 卡片/侧栏面 | `#FFFFFF` |
| 描边 | `#EEF0F6` |
| 文字-主 | `#15172B` |
| 文字-次 | `#646A82` |
| 文字-弱 | `#A9ADC0` |
| 语义-绿 | `#1F9D57` |
| 语义-橙 | `#D97706` |
| 语义-品红 | `#DB2777` |

- 渐变（`acc → acc2`）仅用于 logo、关键主按钮、标题高亮，**不铺底**。
- 圆角：卡片 14px，按钮/输入 10–13px。
- 阴影：柔和长投影，`0 8–12px rgba(40,42,80,.06–.12)`。

### 字体

- 中文展示标题：**得意黑 Smiley Sans**，以本地自托管 woff2 引入（放入 `frontend/src/assets/fonts/` 或 `public/fonts/`，用 `@font-face` 声明），无外网依赖。
- 正文：系统栈 `-apple-system, "PingFang SC", "Microsoft YaHei", sans-serif`（可选叠加 MiSans）。
- 等宽点缀（状态标签、数字）：`"Space Mono", ui-monospace, monospace`（同样优先本地/系统，缺失则降级）。

## 3. 应用外壳（`src/layout/base/`）

窄图标侧栏 → **208px 宽文字侧栏**：

- 顶部：品牌区（渐变 logo 方块 + 名称「深度研究助手」）。
- 中部：导航分组标签 +「图标 + 文字」导航项，当前路由项高亮（主色淡底 + 主色文字 + 主色图标）。
- 底部：账户区（头像 + 名称 + 副标题），`margin-top:auto` 贴底。

涉及文件：`index.tsx`、`index.scss`（`base-layout` 左 padding 94px → 208px、`__sidebar` 宽度同步）、`nav.tsx`、`nav.scss`、`nav-item.tsx`、`nav-item.scss`、`footer.tsx/scss`（按需并入账户区或保留）。

## 4. 导航精简与路由（隐藏三项）

采用「摘入口 + 删路由 + 留源码」：

- `nav.tsx`：移除 `memory`、`knowledge`、`database` 三个导航项，仅保留 `home`、`newchat`、`history`。
- `src/router/routes.tsx`：移除 `/knowledge`、`/memory`、`/database` 三条路由及其对应 `import`。直接访问这些 URL 将命中 `path:'*'` → 重定向 `/404`。
- **保留** `src/pages/knowledge`、`src/pages/memory`、`src/pages/database` 的源码文件（不删除），便于日后恢复。
- 相关图标 import（`IconMemory/IconKnowledge/IconDatabase`）从 `nav.tsx` 移除，asset 文件保留。

## 5. 首页（`src/pages/index/`）

按高保真稿重写 `index.tsx` + `index.module.scss`，**功能与跳转逻辑不变**（仍读 `RESEARCH_TEMPLATES`、点击卡片 `navigate('/chat?prompt=...')`、搜索过滤）：

- Hero 区：状态标签（等宽字体「多 Agent 协同 · Critic 自反思」）+ 主标语（含渐变高亮关键词）+ 副描述 + 极淡网格纹理背景。
- 主搜索框：视觉升级为 Hero 中的大输入框，**保留现有「过滤研究模板」行为**（`searchKeyword` 实时过滤下方卡片），placeholder 仍为搜索模板语义。
  - 注：「输入自由课题文本 → 直接进入聊天」属于新增交互行为，**本次不做、列为后续可选增强**，以守住「不改业务逻辑」红线。若高保真稿中的「开始研究」按钮保留，则其仅在有匹配模板时作为视觉引导，不引入新的跳转逻辑。
- 研究模板：2×4 卡片网格，圆角卡 + 图标徽章 + 悬浮上浮微交互；保留四类模板与各自语义色。

## 6. 聊天页与右侧详情面板（`src/pages/chat/**`）——只换肤

**不重构布局结构**，仅让其视觉与新主题一致：

- 将硬编码颜色/字号/字体替换为新 Token（变量或对齐后的值）。
- 统一圆角、描边、阴影风格。
- 覆盖：`pages/chat/index`、`pages/chat/newchat`、`component/research-detail`、`component/research-process`、`component/step-detail-panel` 等。

## 7. 顺带统一（不改结构）

`pages/auth/login`、`pages/404`、`components/session-drawer`、`components/sender` 等公共组件套用新 Token，保证全站视觉一致。

## 8. 范围红线（不做）

- 不改任何业务逻辑、API 调用、状态管理（valtio store）、路由跳转行为。
- 不删除被隐藏页面的源码。
- 不重构聊天页/详情面板的 DOM 结构与布局。
- 后端零改动。

## 9. 验证

- `npm run build` 通过、`npm run lint` 通过。
- `npm run dev` 本地逐页目测：首页、聊天流程、右侧详情面板、登录页、404。
- 确认导航中三项入口已消失；直接访问 `/knowledge`、`/memory`、`/database` 落 `/404`。
- 确认新字体在标题处生效（本地 woff2 加载成功），正文降级栈正常。

## 10. 受影响文件清单（预估）

- `src/index.css`、`src/antd.scss`（或 App 根 theme）：Token。
- `src/assets/fonts/*`：自托管字体。
- `src/layout/base/*`：外壳重构。
- `src/router/routes.tsx`：删三条路由。
- `src/pages/index/*`：首页重构。
- `src/pages/chat/**`：换肤。
- `src/pages/auth/login/*`、`src/pages/404`、`src/components/session-drawer/*`、`src/components/sender/*`：换肤。
