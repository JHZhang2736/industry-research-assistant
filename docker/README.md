# Docker 中间件编排

本目录包含 **PostgreSQL + Redis + Milvus（含 etcd + MinIO）** 的本地开发环境编排，是项目所有后端依赖的本地副本。

## 服务一览

| 服务 | 镜像 | 用途 | 默认端口（host） |
|------|------|------|-----------------|
| postgres | `postgres:16-alpine` | 业务主库 + LangGraph checkpoint | 5432 |
| redis | `redis:7-alpine` | 缓存、限流、会话 | 6379 |
| etcd | `quay.io/coreos/etcd:v3.5.16` | Milvus 元数据 | 仅集群内 |
| minio | `minio/minio` | Milvus S3 后端 + 项目文件存储 | 9000（API）/ 9001（控制台） |
| milvus | `milvusdb/milvus:v2.4.17` | 向量数据库 | 19530 |
| attu *(可选)* | `zilliz/attu:v2.4.12` | Milvus 可视化 | 8001 |
| pgadmin *(可选)* | `dpage/pgadmin4:8` | PostgreSQL 可视化 | 5050 |

## 快速开始

```bash
# 1. 复制环境变量
cp .env.example .env
# (按需修改密码、端口)

# 2. 启动核心组件
docker compose up -d

# 3. 启动核心组件 + 可视化 UI（Attu、pgAdmin）
docker compose --profile ui up -d

# 4. 查看运行状态
docker compose ps

# 5. 查看日志
docker compose logs -f milvus
```

## 连接信息

容器互访使用服务名（在 `deepresearch` 网络内）：

```
postgresql://deepresearch:deepresearch@postgres:5432/deepresearch
redis://:deepresearch@redis:6379/0
milvus: milvus:19530
minio:  minio:9000
```

从宿主机访问使用 `localhost` + `.env` 中的端口：

```
postgresql://deepresearch:deepresearch@localhost:5432/deepresearch
redis://:deepresearch@localhost:6379/0
milvus: localhost:19530
minio 控制台: http://localhost:9001  (用户名/密码见 .env)
attu:        http://localhost:8001
pgadmin:     http://localhost:5050
```

## 常用操作

```bash
# 停止全部
docker compose down

# 停止并清空数据（危险：所有 volume 一起删）
docker compose down -v

# 只重启某个服务
docker compose restart milvus

# 进入容器
docker exec -it ira-postgres psql -U deepresearch
docker exec -it ira-redis redis-cli -a deepresearch
```

## 注意事项

- **资源占用**：Milvus standalone 启动后大约占 1.5–2 GB 内存，请确认 Docker Desktop 给到足够资源（建议 ≥ 6 GB）。
- **健康检查**：Milvus 启动较慢，依赖 etcd / minio 健康后才会启动，首次拉镜像约需几分钟。
- **数据持久化**：所有有状态服务使用命名 volume（`postgres_data` / `milvus_data` 等），不会随容器删除丢失。
- **凭据安全**：`.env` 已被 `.gitignore` 忽略，不会进入版本控制；生产环境务必替换默认密码。
- **MinIO bucket**：Milvus 启动时会自动在 MinIO 中创建所需 bucket，无需手动初始化。
