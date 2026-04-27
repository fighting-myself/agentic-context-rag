# agentic-context-rag V1 实现设计文档

## 1. 目标
- 构建一个前后端分离的智能问答系统，支持多轮会话记忆、RAG 增强、上下文管理、工具调用入口、文件与知识库管理基础能力。
- 技术栈：LangChain + LangGraph、SQLite + ChromaDB、Redis 缓存、Qwen 模型（默认 `qwen3-vl-plus`）。
- 非功能目标：高召回、低延迟、全链路可观测（trace 日志、滚动日志、统一异常处理）。

## 2. V1 范围

### 2.1 后端能力
- `POST /api/v1/chat`: 多轮对话问答入口。
- `POST /api/v1/knowledge/upsert`: 向知识库写入文档片段。
- `GET /api/v1/sessions/{session_id}/history`: 查询会话历史。
- RAG 检索策略：BM25 + 向量召回，融合重排（简化加权融合）。
- 缓存策略：Redis 查询缓存（问题+会话上下文哈希 -> 回答）。
- 持久化：
  - SQLite: 会话消息、trace 元信息。
  - ChromaDB: 文档向量。

### 2.2 前端能力
- 单页 Web 聊天界面：
  - 创建/输入会话 ID；
  - 输入问题并查看回答；
  - 查看检索来源片段（简化）。

### 2.3 工程化
- `docker-compose` 一键启动（frontend/backend/redis）。
- 清晰 README（启动、配置、架构、性能优化思路）。
- 统一日志：
  - 每请求 trace_id；
  - 日志写文件并滚动；
  - 统一异常捕获并记录。

## 3. 架构设计

### 3.1 模块分层
- `app/api`: HTTP 路由层。
- `app/services`:
  - `chat_service.py`: LangGraph 工作流编排。
  - `retrieval_service.py`: BM25 + 向量融合检索。
  - `kb_service.py`: 文档入库、切片与向量写入。
  - `memory_service.py`: SQLite 会话消息读写。
  - `cache_service.py`: Redis 缓存访问。
- `app/core`:
  - `config.py`: 环境变量配置。
  - `logging.py`: trace 日志配置、滚动策略。
  - `exceptions.py`: 统一异常与处理器。

### 3.2 LangGraph 工作流（V1）
1. 输入用户问题与 session_id；
2. 读取最近 N 轮对话上下文；
3. 执行融合检索（BM25 + 向量）；
4. 命中缓存则直接返回；
5. 未命中则构建提示词，调用 Qwen；
6. 落库消息与 trace，写入缓存。

## 4. 性能与召回策略
- 高召回：
  - TopK: 向量召回 `k=8`，BM25 召回 `k=8`；
  - 融合时按 `0.6*vector + 0.4*bm25` 计算最终分数；
  - 去重后返回 top5 上下文。
- 低延迟：
  - Redis 命中直接短路，减少 LLM 调用。
  - SQLite 建索引（session_id, created_at）。
  - 控制上下文窗口：仅携带最近 8 条会话消息。
- TTFT 优化方向（V1 预留）：
  - 支持流式响应接口；
  - 增加问题归一化缓存键；
  - 引入重排模型按需启用。

## 5. 配置项
- `QWEN_API_KEY`
- `QWEN_MODEL`（默认 `qwen3-vl-plus`）
- `QWEN_BASE_URL`（兼容 OpenAI 接口）
- `REDIS_URL`
- `SQLITE_PATH`
- `CHROMA_PATH`
- `LOG_PATH`
- `LOG_LEVEL`

## 6. 文档更新记录
- 2026-04-27：完成 V1 设计草案，待进入编码实现后补充“实现状态”。

## 7. 本次实现状态（V1）
- 已完成后端基础能力：
  - FastAPI 路由：`/chat`、`/knowledge/upsert`、`/sessions/{session_id}/history`。
  - LangGraph 流程：prepare -> retrieve -> cache -> generate -> persist。
  - 检索融合：向量检索 + BM25 分数融合（0.6/0.4）。
  - 存储：SQLite 会话历史、Chroma 向量库。
  - 缓存：Redis 命中短路返回。
  - 日志：JSON + trace_id + 滚动日志。
  - 异常：统一业务异常与兜底异常处理。
- 已完成前端基础能力：
  - Web 对话页面；
  - 知识写入页面操作；
  - 显示缓存命中状态和上下文数量。
- 已完成工程化：
  - 前后端 Dockerfile；
  - `docker-compose` 集成 `frontend/backend/redis`；
  - README 首版。

## 8. 已知限制与下一步
- 当前 BM25 为全量文档内存打分，文档规模大时需优化为倒排索引或分片策略。
- 当前未实现流式输出（仅预留），后续需增加 streaming 以进一步优化 TTFT。
- 当前未加入工具调用具体业务插件，V1 仅保留流程入口能力。

## 9. V1.1 开发计划（编码前更新）
- 本轮目标：
  - 增加 `SSE` 流式问答接口，降低用户主观等待时间与 TTFT。
  - 增加 trace 持久化表（SQLite），记录每次请求关键性能指标。
  - 增加阶段耗时埋点：检索耗时、模型耗时、总耗时、TTFT、缓存命中。
- 具体改动点：
  - `chat_service.py`：新增流式生成方法与指标采集。
  - `routes.py`：新增 `/chat/stream` 接口，返回 `text/event-stream`。
  - `memory_service.py`：新增 `traces` 表与写入方法。
  - `README.md`：补充流式调用方式与性能日志说明。

## 10. V1.1 实现结果（编码后更新）
- 已完成：
  - 新增 `POST /api/v1/chat/stream`，支持 `SSE` 流式输出（`meta/token/done`）。
  - `chat_service.py` 增加 `stream_ask` 异步流式方法，并支持缓存命中直返。
  - `memory_service.py` 增加 `traces` 表与 `add_trace` 写入方法。
  - 每次问答记录关键性能指标：`retrieve_ms`、`llm_ms`、`total_ms`、`ttft_ms`、`cache_hit`。
  - README 已补充流式接口说明与 trace 指标落库说明。
- 本轮收益：
  - 主观等待下降：可边生成边展示。
  - 性能可观测性增强：为后续 TTFT/吞吐优化提供真实数据基础。

## 11. V1.2 开发计划（编码前更新）
- 本轮目标：
  - 前端接入 SSE 流式渲染，实时显示 token。
  - 增加 traces 查询接口，便于按会话查看性能数据。
  - 检索提速：BM25 从“全量”改为“向量候选集内打分”。
- 具体改动点：
  - `frontend/src/api.js`、`frontend/src/App.jsx`：新增流式请求与实时渲染逻辑。
  - `memory_service.py`、`routes.py`：新增 traces 查询能力。
  - `retrieval_service.py`：改为两阶段检索（vector candidate -> BM25 rerank）。

## 12. V1.2 实现结果（编码后更新）
- 已完成：
  - 前端改为调用 `/chat/stream`，支持 token 级实时渲染。
  - 新增 `GET /api/v1/traces/{session_id}`，可按会话查看性能记录。
  - 检索改为“两阶段”：先向量召回候选，再候选内 BM25 打分融合，降低大库场景延迟。
  - 前端新增“查看性能”按钮，展示最近 trace 指标。
- 本轮收益：
  - 体验上：回答可逐字出现，等待更可感知。
  - 性能上：避免 BM25 全量扫描，提升检索阶段速度与可扩展性。

## 13. V1.3 开发计划（编码前更新）
- 本轮目标：
  - 增加缓存键归一化策略，提升近义问法与格式差异场景下命中率。
  - 增加 traces 聚合统计接口，输出命中率、P50/P95（total 与 ttft）。
  - 前端增加简单性能趋势视图（最近 N 次 total_ms 折线）。
- 具体改动点：
  - `cache_service.py`：增加 query/history 归一化后参与 key 计算。
  - `memory_service.py`、`routes.py`：新增 traces 聚合计算与 API。
  - `frontend/src/api.js`、`frontend/src/App.jsx`：新增聚合请求与趋势图渲染。

## 14. V1.3 实现结果（编码后更新）
- 已完成：
  - 缓存 key 归一化：对 query 与最近历史进行清洗（大小写、空白、标点），提升缓存复用能力。
  - 新增聚合接口：`GET /api/v1/traces/{session_id}/stats`，返回命中率、P50/P95。
  - 前端新增聚合展示与 total_ms 趋势折线图。
- 本轮收益：
  - 命中率提升：语义不变但写法不同的问题更容易命中缓存。
  - 观测增强：可直接识别尾延迟（P95）并跟踪性能波动趋势。

## 15. V1.4 开发计划（编码前更新）
- 本轮目标：
  - 增加多轮上下文压缩策略，降低 prompt token 开销。
  - 增加检索结果去重与多样性控制，兼顾相关性与覆盖度。
  - 提供轻量压测脚本与基准报告，便于量化优化收益。
- 具体改动点：
  - `config.py`、`chat_service.py`：新增上下文压缩参数与压缩逻辑。
  - `retrieval_service.py`：新增相似内容去重、按来源多样性限制。
  - `scripts/benchmark.py`：新增压测脚本，输出 JSON 报告。

## 16. V1.4 实现结果（编码后更新）
- 已完成：
  - `chat_service.py` 增加历史与检索上下文压缩，控制参与 prompt 的文本规模。
  - `retrieval_service.py` 增加基于 Jaccard 的相似片段去重与 source 配额限制。
  - 新增 `scripts/benchmark.py` 压测脚本，支持多轮调用并输出基准报告。
  - `config.py` 补充压缩/去重相关配置项，便于后续调优。
- 本轮收益：
  - 降低 prompt 冗余，减少模型输入负担并改善响应稳定性。
  - 检索结果覆盖更均衡，减少重复片段占位，提高有效召回利用率。
  - 建立了可重复压测入口，便于持续追踪优化效果。

## 17. V1.5 开发计划（编码前更新）
- 本轮目标：
  - 增加 query rewrite 与检索意图分类，改善多轮追问场景召回质量。
  - 增加回答引用片段与置信度输出，提升可解释性。
  - 增加基准报告对比脚本，支持优化前后量化对比。
- 具体改动点：
  - `chat_service.py`：新增 rewrite、intent、citation、confidence 逻辑。
  - `frontend/src/App.jsx`：展示改写问题、意图、置信度和引用。
  - `scripts/compare_benchmarks.py`：读取两份 benchmark JSON 并输出对比报告。

## 18. V1.5 实现结果（编码后更新）
- 已完成：
  - `chat_service.py` 新增 query rewrite、意图分类、引用构建与置信度估计。
  - 流式/非流式接口统一返回 `intent`、`rewritten_question`、`confidence`、`citations`。
  - 前端消息面板可展示意图、改写问题、置信度与引用摘要。
  - 新增 `scripts/compare_benchmarks.py`，支持两份基准报告自动对比输出。
- 本轮收益：
  - 对多轮追问的检索 query 更稳定，减少指代导致的召回偏移。
  - 回答可解释性更高，可快速定位来源片段并辅助人工校验。
  - 性能优化形成“压测+对比”闭环，便于持续迭代。

## 19. 环境配置调整（编码前更新）
- 本轮目标：
  - 将 Redis 连接切换为 Upstash 远程 `rediss://` 地址。
- 具体改动点：
  - 更新 `backend/.env.example` 的 `REDIS_URL`。
  - 在 `README.md` 补充 Upstash Redis URL 使用说明。

## 20. 环境配置调整（编码后更新）
- 已完成：
  - `backend/.env.example` 已切换为你提供的 Upstash `rediss://` Redis URL。
  - `README.md` 已补充 Upstash Redis URL 使用提醒（使用 Redis 协议地址而非 REST 地址）。

## 21. 部署联通检查与端口调整（编码前更新）
- 本轮目标：
  - 为阿里云单机部署校验前后端联通链路。
  - 调整对外端口：前端 `8500`，后端 `8501`。
- 具体改动点：
  - `docker-compose.yml`：修改前后端映射端口。
  - `frontend/nginx.conf`：增加 `/api/` 反向代理到后端容器。
  - `frontend/src/api.js`：默认走同源 `/api/v1`，避免写死 localhost。

## 22. 部署联通检查与端口调整（编码后更新）
- 已完成：
  - `docker-compose.yml` 端口改为前端 `8500:80`、后端 `8501:8000`。
  - `frontend/nginx.conf` 新增 `/api/` 反向代理到 `http://backend:8000/api/`。
  - `frontend/src/api.js` 默认 API 基址改为 `/api/v1`（同源代理）。
  - `README.md` 已同步更新部署端口与联通说明。

## 23. 部署命令文档补充（编码前更新）
- 本轮目标：
  - 在 `README.md` 明确补充：
    - 前后端镜像构建命令；
    - 分别启动前后端容器命令；
    - 前后端不在同一网络时的网络创建与加入方式。

## 24. 部署命令文档补充（编码后更新）
- 已完成：
  - `README.md` 新增“分别构建前后端镜像”命令。
  - `README.md` 新增“分别启动前后端容器（同一网络）”完整命令。
  - `README.md` 新增“前后端不在同一网络时”网络创建、连接、断开示例命令。

## 25. 依赖冲突修复（编码前更新）
- 本轮目标：
  - 修复 Docker 构建时 `fastapi` 与 `chromadb` 的版本冲突。
- 具体改动点：
  - 调整 `backend/requirements.txt` 中 `fastapi` 版本，使其与 `chromadb==1.0.7` 兼容。

## 26. 依赖冲突修复（编码后更新）
- 已完成：
  - `backend/requirements.txt` 已将 `fastapi` 从 `0.115.12` 调整为 `0.115.9`。
  - 该版本与 `chromadb==1.0.7` 的依赖约束一致，解决构建阶段冲突。

## 27. 启动异常修复（编码前更新）
- 本轮目标：
  - 修复后端容器启动时报错 `ModuleNotFoundError: pythonjsonlogger.json`。
- 具体改动点：
  - 修正 `backend/app/core/logging.py` 中 `python-json-logger` 的导入路径。

## 28. 启动异常修复（编码后更新）
- 已完成：
  - `backend/app/core/logging.py` 导入已改为 `from pythonjsonlogger.jsonlogger import JsonFormatter`。
  - 与 `python-json-logger==2.0.7` 的实际模块路径一致，可消除该启动异常。

## 29. 前端 Nginx upstream 可配置（编码前更新）
- 本轮目标：
  - 修复单独部署时 Nginx 报错 `host not found in upstream "backend"`。
- 具体改动点：
  - 使用官方镜像 `templates` + `envsubst`，通过环境变量 `BACKEND_HOST` 指定后端主机名。
  - `docker-compose.yml` 为 frontend 显式设置 `BACKEND_HOST=backend`。
  - `README.md` 单独 `docker run` 示例增加 `-e BACKEND_HOST=agentic-rag-backend`。

## 30. 前端 Nginx upstream 可配置（编码后更新）
- 已完成：
  - 新增 `frontend/templates/default.conf.template`，`proxy_pass` 使用 `${BACKEND_HOST}`。
  - `frontend/Dockerfile` 默认 `ENV BACKEND_HOST=backend`，并复制模板到 `/etc/nginx/templates/`。
  - 删除写死 upstream 的 `frontend/nginx.conf`，避免与单独部署场景冲突。

## 31. 知识库管理与 UI 改版（编码前更新）
- 本轮目标：
  - 前端界面现代化（布局、配色、组件层次）。
  - 支持文件上传入库、可配置分块大小与重叠。
  - 支持创建/列出/删除知识库，以及按库管理文档（列表与删除）。
  - 对话绑定当前选中的知识库（`kb_id`），检索与缓存键随库变化。
- 具体改动点：
  - SQLite：`knowledge_bases`、`knowledge_documents` 表；初始化默认库 `default`。
  - Chroma：按 `kb_{id}` 分集合存储向量；删除库/文档时同步清理向量。
  - API：`/knowledge-bases` CRUD、`/knowledge-bases/{id}/upload` 多部分上传、`/knowledge-bases/{id}/documents` 列表与删除。
  - 聊天请求体增加 `kb_id`；`CacheService.build_key` 纳入 `kb_id`。
  - 前端：`App.css` + 重构 `App.jsx`、`api.js`。

## 32. 知识库管理与 UI 改版（编码后更新）
- 已完成：
  - 后端：`MemoryService` 增加知识库与文档元数据表；`KnowledgeBaseService` 按 `kb_{id}` 分 Chroma 集合；检索与对话支持 `kb_id`；`python-multipart` 支持上传。
  - API：`POST/GET/DELETE /knowledge-bases`、`GET/DELETE .../documents`、`POST .../upload`；`/knowledge/upsert` 与 `/chat` 支持 `kb_id` 与分块参数；文本入库写入文档记录。
  - 前端：深色主题双栏布局、知识库切换/创建/删除、分块参数、拖放上传、文档表、对话气泡与性能区。
