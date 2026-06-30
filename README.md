# WorkfloAgent — 企业智能工单处理系统

> 基于 Multi-Agent + RAG 的企业级工单自动化处理系统。  
> 用户提交工单 → AI 自动分类 → 知识库检索 → 工具执行 → 回复用户。  
> 完整工单生命周期管理：提报、分配、处理、审批、SLA 跟踪、反馈闭环。

---

## 功能特性

### 🤖 AI 自动处理
| 能力 | 说明 |
|------|------|
| **智能分类** | LLM 自动判断工单类别（IT/HR/财务/运维/其他），支持用户指定部门 |
| **RAG 检索** | 多路召回（关键词 + 向量）+ RRF 融合排序 + 精排，按部门隔离知识库 |
| **ReAct 执行** | 最多 5 轮工具调用循环，自动查询/更新/通知/转人工 |
| **流式处理** | SSE 实时推送处理进度，前端逐步骤展示 |

### 📋 工单生命周期
- 提报 → 分类 → 自动处理 → 用户确认/转人工
- 工程师接单 → 处理 → 解决 → 关闭 → 重新打开
- 审批流程：HR/财务类工单自动进入审批链
- **SLA 管理**：按优先级自动计算截止时间，实时超时检测
- **批量操作**：批量关闭、批量接单、批量转人工

### 📊 可观测性
- **全链路追踪**：每次处理生成唯一 trace_id，记录每一步输入输出和耗时
- **Prometheus 指标**：工单处理量、耗时、工具调用、LLM 用量、RAG 命中率
- **仪表盘**：系统运行概览（处理量、分类分布、自动解决率、反馈统计）
- **CSV 导出**：工单数据一键导出

### 🔄 自我进化
- **反馈驱动**：用户评分 → 低评分自动触发复盘 → 知识补全 → 模式提取
- **知识缺口检测**：RAG 零结果时自动检测并建议补充知识库

### 🔌 集成
- **飞书 / 企业微信 / 钉钉**：Bot 消息回调 + 卡片回复
- **MCP 协议**：支持 Model Context Protocol 标准工具调用

---

## 快速开始

### 前置要求

- Python 3.11+
- LLM API Key（支持 DeepSeek / DashScope / OpenAI / GLM / 月之暗面 等）

### 1 分钟启动

```bash
# 1. 克隆项目
git clone https://github.com/yourname/WorkfloAgent.git
cd WorkfloAgent

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 API Key
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY

# 4. 启动服务
uvicorn ticket_agent.main:app --reload --port 8000
```

打开 http://localhost:8000 访问 Web 界面，或 http://localhost:8000/docs 查看 Swagger 文档。

---

## 使用指南

### Web 界面

| 菜单 | 功能 | 权限 |
|------|------|------|
| **提交工单** | 输入内容+选部门（可选），AI 自动处理 | 所有人 |
| **我的工单** | 员工看自己的，工程师看待办 | 登录后 |
| **部门队列** | 部门内待处理工单 | 工程师+ |
| **待审批** | HR/财务工单审批 | 经理+ |
| **工单记录** | 全部工单历史，支持批量操作 | 登录后 |
| **仪表盘** | 系统运行概览数据 | 登录后 |
| **知识库** | 企业知识文档管理 | 登录后 |
| **模型设置** | 运行时切换 AI 模型，无需重启 | 登录后 |

### 测试账号

种子数据默认创建以下账号（密码均为 `123456`）：

| 角色 | 账号 | 权限 |
|------|------|------|
| 管理员 | `admin` | 全部权限 |
| IT 工程师 | `it_zhang` | IT 工单处理 |
| HR 经理 | `hr_wang` | HR 审批+处理 |
| 财务经理 | `finance_li` | 财务审批+处理 |
| 普通员工 | `zhangsan` | 提报工单 |

### API 概览

```
工单处理
  POST   /ticket                    提交工单（AI 自动处理）
  POST   /api/ticket/public         免登录提交工单
  GET    /ticket/{id}               查询工单详情
  GET    /tickets                   工单列表
  POST   /ticket/{id}/assign       工程师接单
  POST   /ticket/{id}/resolve      标记已解决
  POST   /ticket/{id}/close        关闭归档
  POST   /ticket/{id}/reopen       重新打开
  POST   /ticket/{id}/confirm      用户确认已解决
  POST   /ticket/{id}/reject       用户转人工
  GET    /trace/{id}               Agent 执行链路
  POST   /tickets/batch/close      批量关闭
  POST   /tickets/batch/assign     批量接单
  POST   /tickets/batch/escalate   批量转人工
  GET    /tickets/export           导出 CSV

知识库
  GET    /knowledge                文档列表
  POST   /knowledge                新增文档（经理+）
  PUT    /knowledge/{id}           更新文档（经理+）
  DELETE /knowledge/{id}           删除文档（经理+）

组织管理
  GET    /api/org/users            用户列表
  GET    /api/org/departments      部门列表
  GET    /api/org/queue/my         我的工单
  GET    /api/org/queue/department/{id}  部门队列
  POST   /api/org/approvals/process      审批操作

反馈与进化
  POST   /feedback                 提交反馈
  GET    /feedback/stats           反馈统计
  GET    /patterns                 处理模式列表

系统
  POST   /auth/login               登录
  POST   /auth/register            注册（管理员）
  POST   /auth/change-password     修改密码
  GET    /stats                    系统统计
  GET    /categories               工单分类
  POST   /switch_model             切换 AI 模型
  GET    /health                   健康检查
```

---

## Docker 部署

```bash
# 构建并启动
docker compose up --build

# 仅启动核心服务（无需 Qdrant/Redis）
docker compose up ticket-agent

# 完整体验（含向量数据库）
docker compose --profile full up
```

Docker Compose 自动处理：
- SQLite 数据持久化（`data/` 目录）
- Trace 文件持久化（`traces/` 目录）
- 健康检查 + 自动重启
- 可选 Qdrant 向量数据库
- 可选 Redis 缓存

---

## 技术栈

| 层级 | 技术 |
|------|------|
| **语言** | Python 3.11+ |
| **Web 框架** | FastAPI + Uvicorn |
| **AI Agent** | ReAct 循环 + Function Calling |
| **工作流** | Linear 编排 / LangGraph 状态机 |
| **RAG** | 关键词检索 + Qdrant 向量 + RRF 融合 + 精排 |
| **LLM** | DashScope / OpenAI 兼容（DeepSeek/GLM/Kimi/零一万物） |
| **数据库** | SQLite（开发） / MySQL（生产） |
| **ORM** | SQLAlchemy 2.0 |
| **认证** | JWT + bcrypt + RBAC（4 角色） |
| **前端** | 纯 HTML + Tailwind CSS（SPA，无框架依赖） |
| **监控** | Prometheus + JSONL 全链路追踪 |
| **集成** | 飞书 / 企业微信 / 钉钉 Bot |
| **部署** | Docker + Docker Compose |

---

## 项目结构

```
WorkfloAgent/
├── ticket_agent/              # 核心应用
│   ├── main.py               # FastAPI 入口 + 生命周期管理
│   ├── api/                   # REST API 路由（6 个子模块）
│   │   ├── routes.py          #   路由聚合
│   │   ├── routes_ticket.py   #   工单 CRUD
│   │   ├── routes_knowledge.py#   知识库管理
│   │   ├── routes_feedback.py #   反馈与模式
│   │   ├── routes_model.py    #   模型配置
│   │   ├── routes_misc.py     #   统计/上传/分类
│   │   ├── routes_org.py      #   组织/队列/审批
│   │   ├── schemas.py         #   Pydantic 模型
│   │   └── deps.py            #   共享依赖
│   ├── agents/                # 分类 Agent + 执行 Agent
│   ├── coordinator/           # 线性编排 + LangGraph 编排
│   ├── tools/                 # 工单工具（查/改/通知/转人工/检索）
│   ├── knowledge/             # 知识库存储 + 检索 + Embedding
│   ├── models/                # 工单实体 + 状态枚举 + 配置存储
│   ├── database/              # SQLAlchemy ORM + 迁移 + 种子数据
│   ├── repository/            # 数据访问层
│   ├── memory/                # 对话记忆 + 模式提取
│   ├── feedback/              # 反馈存储
│   ├── evolution/             # 复盘/准确率追踪/知识缺口检测
│   ├── monitoring/            # Prometheus 指标
│   ├── streaming/             # SSE 流式处理
│   ├── scheduler/             # 定时任务调度
│   ├── sla/                   # SLA 配置与计算
│   ├── security/              # 工具调用防护
│   ├── auth/                  # JWT 认证 + 角色权限
│   ├── integrations/          # 飞书/企微/钉钉 Bot
│   ├── mcp/                   # MCP 协议支持
│   └── static/index.html      # Web 前端（Tailwind CSS SPA）
│
├── agents/                    # Agent 框架基类
├── llm/                       # LLM 多模型抽象（7+ Provider）
├── tools/                     # 工具系统（基类+注册表+熔断器）
├── rag/                       # RAG 检索引擎
├── memory/                    # 记忆系统基类
├── skills/                    # 技能单元
├── utils/                     # 日志/Trace/JSON解析/令牌桶限流
├── config/                    # YAML 配置管理
├── tests/                     # 234 个测试用例
├── .env.example               # 环境变量模板
├── docker-compose.yml         # Docker 编排
└── requirements.txt           # Python 依赖
```

---

## 配置说明

| 环境变量 | 必填 | 默认值 | 说明 |
|----------|------|--------|------|
| `LLM_API_KEY` | ✅ | - | LLM API Key |
| `LLM_PROVIDER` | | `openai` | Provider 类型 |
| `LLM_MODEL` | | `deepseek-chat` | 模型名称 |
| `LLM_BASE_URL` | | `https://api.deepseek.com/v1` | API 地址 |
| `DATABASE_URL` | | `sqlite:///data/ticket_agent.db` | 数据库连接 |
| `JWT_SECRET` | | 自动生成 | JWT 签名密钥 |
| `MODEL_CONFIG_KEY` | | 自动生成 | API Key 加密密钥 |
| `QDRANT_ENABLED` | | `false` | 启用向量检索 |
| `AGENT_TRACE_ENABLED` | | `true` | 启用全链路追踪 |

---

## License

MIT
