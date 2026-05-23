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
- **关系型数据库**：PostgreSQL / MySQL（业务数据、会话、用户）
- **向量数据库**：Milvus（知识库向量检索）
- **缓存**：Redis（会话、限流、热点数据）
- **文件存储**：File Storage（原始文档、报告产物）

## 技术特征
- 架构：多智能体（Multi-Agent）协作，基于 LangGraph 编排
- 形态：AI 深度研究系统（Deep Research），支持 SSE 流式输出与断点续跑（checkpoint/resume）
- 工作流：信息收集 → 数据分析 → 报告撰写
