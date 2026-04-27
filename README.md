# agentic-context-rag (V1)

基于 LangChain + LangGraph 的智能问答项目，支持多轮记忆、RAG（BM25+向量）、Redis 缓存、SQLite/Chroma 存储，以及前后端分离与容器部署。

## 1. 功能概览
- 多轮会话：`session_id` 维度保存历史消息（SQLite）。
- RAG 检索：向量召回 + BM25 融合排序（Chroma + rank-bm25）。
- 缓存：Redis 命中后直接返回，减少模型调用延迟。
- 模型：默认 `qwen3-vl-plus`，兼容 OpenAI-style API。
- 可观测性：统一 JSON 日志、trace_id、滚动日志、统一异常处理。

## 2. 项目结构
- `backend/`: FastAPI + LangGraph 后端。
- `frontend/`: React + Vite 前端。
- `docs/design.md`: 设计与实现文档。
- `docker-compose.yml`: 一键启动服务。

## 3. 快速启动

### 3.1 本地启动（推荐先调试）
1. 后端
   - `cd backend`
   - `python -m venv .venv`
   - Windows: `.venv\Scripts\activate`
   - `pip install -r requirements.txt`
   - 复制 `.env.example` 为 `.env` 并配置 `QWEN_API_KEY`
   - 若使用 Upstash，`REDIS_URL` 使用 `rediss://` 的 Redis URL（不是 REST 的 https 地址）
   - `uvicorn app.main:app --reload --port 8000`
2. 前端
   - `cd frontend`
   - `npm install`
   - `npm run dev`

### 3.2 Docker 启动
- 在项目根目录运行：`docker compose up --build`
- 前端: `http://localhost:8500`
- 后端: `http://localhost:8501/healthz`
- 前端通过 Nginx 反向代理 `/api/*` 到后端容器（同机部署默认已打通）。
- 说明：`docker compose` 下 Compose 服务名为 `backend`，前端镜像默认 `BACKEND_HOST=backend`；若你单独 `docker run` 且后端容器名不是 `backend`，启动前端时必须设置 `-e BACKEND_HOST=<后端容器名>`。

### 3.3 分别构建前后端镜像
- 构建后端镜像（项目根目录执行）：
  - `docker build -t agentic-rag-backend:latest ./backend`
- 构建前端镜像（项目根目录执行）：
  - `docker build -t agentic-rag-frontend:latest ./frontend`

### 3.4 分别启动前后端容器（同一网络）
1. 先创建自定义网络（如不存在）：
   - `docker network create agentic-rag-net`
2. 启动后端：
   - `docker run -d --name agentic-rag-backend --network agentic-rag-net --env-file ./backend/.env.example -p 8501:8000 -v ./backend/data:/app/backend/data -v ./backend/logs:/app/backend/logs agentic-rag-backend:latest`
3. 启动前端（`BACKEND_HOST` 必须与后端容器名一致，否则 Nginx 无法解析 upstream）：
   - `docker run -d --name agentic-rag-frontend --network agentic-rag-net -e BACKEND_HOST=agentic-rag-backend -p 8500:80 agentic-rag-frontend:latest`

### 3.5 前后端不在同一网络时（必须先创建并加入同一网络）
- 如果容器已在不同网络，先创建目标网络：
  - `docker network create agentic-rag-net`
- 将后端加入目标网络：
  - `docker network connect agentic-rag-net agentic-rag-backend`
- 将前端加入目标网络：
  - `docker network connect agentic-rag-net agentic-rag-frontend`
- 可选：从旧网络移除
  - `docker network disconnect <old_network> agentic-rag-backend`
  - `docker network disconnect <old_network> agentic-rag-frontend`

## 4. API 简介
- `GET /api/v1/knowledge-bases`：列出知识库。
- `POST /api/v1/knowledge-bases`：创建知识库，请求体 `{"name":"名称","description":""}`。
- `DELETE /api/v1/knowledge-bases/{kb_id}`：删除知识库（不可删 `default`）。
- `GET /api/v1/knowledge-bases/{kb_id}/documents`：文档列表。
- `DELETE /api/v1/knowledge-bases/{kb_id}/documents/{doc_id}`：删除文档及对应向量。
- `POST /api/v1/knowledge-bases/{kb_id}/upload`：`multipart/form-data`，字段 `file`、`chunk_size`、`overlap`。
- `POST /api/v1/knowledge/upsert`
  - 请求体：`{"kb_id":"default","chunk_size":500,"overlap":80,"docs":[{"text":"知识内容","source":"manual"}]}`
- `POST /api/v1/chat`
  - 请求体：`{"session_id":"s1","kb_id":"default","question":"你的问题"}`
- `POST /api/v1/chat/stream`
  - 请求体：`{"session_id":"s1","kb_id":"default","question":"你的问题"}`
  - 返回：`SSE(text/event-stream)`，事件类型包含 `meta/token/done`
- `GET /api/v1/sessions/{session_id}/history`
- `GET /api/v1/traces/{session_id}?limit=20`
  - 返回该会话最近性能指标记录。
- `GET /api/v1/traces/{session_id}/stats?limit=100`
  - 返回会话聚合统计：命中率、P50/P95（total 与 ttft）。

## 5. 日志与排障
- 日志文件默认：`backend/logs/app.log`
- 采用 RotatingFileHandler，默认 5MB * 5 份滚动。
- 每次请求返回 `trace_id`，可用于日志检索。
- 性能指标已落 SQLite `traces` 表：`retrieve_ms/llm_ms/total_ms/ttft_ms/cache_hit`。

## 6. 性能优化方向（下一步）
- 增加流式响应以优化 TTFT。
- 引入 query rewrite 与缓存 key 归一化。
- 可选增加 reranker（在性能预算内启用）。

## 7. V1.3 增强
- 缓存键增加归一化：大小写、空白、标点差异不再显著影响命中。
- traces 提供聚合统计接口，便于快速看命中率与尾延迟。
- 前端提供最近 total_ms 趋势折线，便于观察性能波动。

## 8. V1.4 增强
- 增加多轮上下文压缩（历史轮次与文本长度可配置），降低 prompt 膨胀。
- 增加检索去重与多样性控制（Jaccard 去重 + source 配额）。
- 新增轻量压测脚本：`scripts/benchmark.py`
  - 示例：`python scripts/benchmark.py --base-url http://localhost:8000/api/v1 --rounds 20`
  - 输出报告：`backend/data/benchmark-report.json`

## 9. V1.5 增强
- 增加 query rewrite 与检索意图分类（comparison/how_to/why/fact）。
- 问答结果增加 `rewritten_question`、`intent`、`confidence`、`citations`。
- 前端展示改写问题、置信度与引用片段。
- 新增基准对比脚本：`scripts/compare_benchmarks.py`
  - 示例：`python scripts/compare_benchmarks.py --baseline backend/data/benchmark-a.json --candidate backend/data/benchmark-b.json`
