# 信息行业分析助手（Industry Research Assistant）

> 多智能体协作的 AI 深度研究系统，自动完成从信息收集、数据分析到报告撰写的完整研究流程。

## 项目定位

专为 **行业分析师、投资研究人员、企业战略部门** 设计，基于多智能体（Multi-Agent）协作架构，端到端交付深度研究产出。

## 应用场景

- **行业研究报告生成**：调研市场规模、竞争格局、技术趋势，输出投行标准的深度报告
- **企业竞争分析**：分析市场地位、业务模式、财务表现，横向对比竞争对手
- **政策影响评估**：追踪政策变化对行业的影响，预测政策趋势
- **技术趋势研判**：识别新兴技术的发展阶段，评估技术成熟度与商业化前景

## 技术架构

| 层级 | 技术选型 |
|------|---------|
| 前端 | React 18 + TypeScript + Ant Design + ECharts + Recharts + react-markdown + Zustand + Axios |
| API 网关 | FastAPI（SSE 流式输出 / checkpoint 断点续跑） |
| 多智能体编排 | LangGraph |
| 辅助服务 | Text2SQL、新闻采集（定时任务）、知识库管理（向量检索） |
| 关系型数据库 | PostgreSQL（LangGraph 官方 checkpointer 支持） |
| 向量数据库 | Milvus |
| 缓存 | Redis |
| 文件存储 | MinIO（兼任 Milvus 后端） |

## 目录结构

```
.
├── backend/      # FastAPI 后端 + LangGraph 多智能体编排
├── frontend/     # React 前端
├── docker/       # docker-compose 与中间件编排
├── docs/         # 设计文档、API 文档
├── CLAUDE.md     # Claude Code 项目上下文
└── README.md
```

## 快速开始

> 项目处于早期开发阶段，相关命令将随各层落地陆续补充。

```bash
# 1. 启动中间件（PostgreSQL / Redis / Milvus + etcd + MinIO）
cd docker
cp .env.example .env
docker compose up -d
# 详见 docker/README.md

# 2. 启动后端
cd ../backend
# TODO: 待补充

# 3. 启动前端
cd ../frontend
# TODO: 待补充
```

## 开发路线

- [x] Docker 中间件编排（PostgreSQL / Redis / Milvus + etcd + MinIO）
- [ ] 后端脚手架（FastAPI + 配置 + 日志 + DB 连接）
- [ ] LLM 接入抽象层
- [ ] 工具集（Web 搜索、网页抓取、文档解析）
- [ ] 知识库与 RAG 检索
- [ ] LangGraph 多智能体编排
- [ ] 业务工作流（四大研究场景）
- [ ] API 接口 + SSE 推送
- [ ] 前端对接

## License

暂未发布开源协议，仓库内代码默认保留全部权利。
