"""
企业工单智能处理 Agent - FastAPI 服务入口

启动方式：
    # 开发模式
    uvicorn ticket_agent.main:app --reload --port 8000

    # 使用 DashScope / OpenAI 兼容接口
    export LLM_API_KEY=your-api-key
    uvicorn ticket_agent.main:app --port 8000

初始化流程：
  1. 加载配置（环境变量 + YAML）
  2. 初始化数据库
  3. 初始化 LLM + Memory
  4. 创建 Coordinator（编排中枢）
  5. 启动调度器 + 进化执行器
  6. 注册路由和中间件
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from config.loader import get_settings
from llm import create_llm
from memory import LocalMemory
from utils.logger import get_logger

from ticket_agent.coordinator.linear import LinearCoordinator
from ticket_agent.api.routes import router
from ticket_agent.api.deps import set_coordinator
from ticket_agent.api.routes_org import router as org_router
from ticket_agent.auth import router as auth_router
from ticket_agent.monitoring import init_monitoring

# 飞书集成（可选）
try:
    from ticket_agent.integrations.feishu import router as feishu_router
    from ticket_agent.integrations.feishu import set_coordinator as set_feishu_bot_coordinator
    FEISHU_AVAILABLE = True
except ImportError:
    FEISHU_AVAILABLE = False
    feishu_router = None

# 企业微信集成（可选）
try:
    from ticket_agent.integrations.wecom import router as wecom_router
    from ticket_agent.integrations.wecom import set_coordinator as set_wecom_coordinator
    WECOM_AVAILABLE = True
except ImportError:
    WECOM_AVAILABLE = False
    wecom_router = None

# 钉钉集成（可选）
try:
    from ticket_agent.integrations.dingtalk import router as dingtalk_router
    from ticket_agent.integrations.dingtalk import set_coordinator as set_dingtalk_coordinator
    DINGTALK_AVAILABLE = True
except ImportError:
    DINGTALK_AVAILABLE = False
    dingtalk_router = None

logger = get_logger("ticket_agent")


def _build_llm_from_env():
    """
    从环境变量 / settings.yaml 构建 LLM 实例。

    优先级：环境变量 > settings.yaml > 默认值
    """
    provider = os.getenv("LLM_PROVIDER") or "dashscope"
    model = os.getenv("LLM_MODEL") or "qwen-plus"
    api_key = os.getenv("LLM_API_KEY") or ""
    base_url = os.getenv("LLM_BASE_URL") or ""

    if not api_key:
        # 降级到 settings.yaml
        try:
            settings = get_settings(config_dir="config")
            if settings.llm.api_key:
                api_key = settings.llm.api_key
                provider = os.getenv("LLM_PROVIDER") or settings.llm.provider or provider
                model = os.getenv("LLM_MODEL") or settings.llm.model or model
                base_url = os.getenv("LLM_BASE_URL") or settings.llm.base_url or base_url
        except Exception:
            pass

    if not api_key:
        logger.warning("未配置 LLM API Key，请在环境变量 LLM_API_KEY 或 settings.yaml 中设置")

    return create_llm({
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "base_url": base_url or None,
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0.3")),
    })


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """应用生命周期管理"""
    logger.info("=" * 50)
    logger.info("企业工单智能处理 Agent 启动中...")
    logger.info("=" * 50)

    # 初始化 LLM
    llm = _build_llm_from_env()

    # 初始化记忆
    memory = LocalMemory(max_messages=20)

    # 初始化数据库
    logger.info("初始化数据库...")
    try:
        from ticket_agent.database import init_db
        from ticket_agent.database.seed import run_all as seed_all

        init_db()
        seed_all()
        logger.info("数据库就绪")
    except Exception as e:
        logger.warning(f"数据库初始化异常: {e}（如未配置 MySQL 将使用 SQLite 回退）")

    # ── 初始化 Qdrant 向量检索（P0 优化） ──
    qdrant_retriever = None
    qdrant_enabled = os.getenv("QDRANT_ENABLED", "false").lower() in ("1", "true", "yes")
    if qdrant_enabled:
        try:
            from rag.vector_store import QdrantVectorStore
            from rag.embeddings import create_embedding
            from rag.retriever import Retriever

            embedding = create_embedding(
                provider=os.getenv("EMBEDDING_PROVIDER", "dashscope"),
                model=os.getenv("EMBEDDING_MODEL", "text-embedding-v2"),
                api_key=os.getenv("EMBEDDING_API_KEY") or os.getenv("LLM_API_KEY", ""),
            )
            vector_store = QdrantVectorStore(
                collection_name="ticket_knowledge",
                embedding=embedding,
                host=os.getenv("QDRANT_HOST", "localhost"),
                port=int(os.getenv("QDRANT_PORT", "6333")),
                embedding_dim=1536,
            )
            qdrant_retriever = Retriever(vector_store=vector_store, top_k=10)
            logger.info("Qdrant 向量检索已就绪")
        except Exception as e:
            logger.warning(f"Qdrant 初始化失败（将使用关键词检索）: {e}")

    # ── 初始化 Cross-encoder 精排（P1 优化） ──
    reranker = None
    if os.getenv("CROSS_ENCODER_ENABLED", "false").lower() in ("1", "true", "yes"):
        try:
            from rag.reranker import CrossEncoderReranker
            reranker_mode = os.getenv("CROSS_ENCODER_MODE", "llm")
            reranker = CrossEncoderReranker(
                mode=reranker_mode,
                model_name=os.getenv("CROSS_ENCODER_MODEL", ""),
                llm=llm if reranker_mode == "llm" else None,
            )
            logger.info(f"Cross-encoder 精排已就绪 (mode={reranker_mode})")
        except Exception as e:
            logger.warning(f"Cross-encoder 初始化失败: {e}")

    # 初始化 Coordinator（支持 Linear / LangGraph 两种编排）
    use_langgraph = os.getenv("USE_LANGGRAPH", "false").lower() in ("1", "true", "yes")
    coordinator_kwargs = dict(
        llm=llm,
        memory=memory,
        rag_top_k=5,
        max_tool_rounds=5,
        use_qdrant=qdrant_enabled,
    )

    # ── 多智能体独立模型（环境变量覆盖）──
    # 用户可设置 CLASSIFIER_LLM_MODEL=gpt-4o-mini 单独控制分类模型
    # 未设置时所有 Agent 共用同一个 llm
    from llm.provider_map import create_llm_from_model

    classifier_model = os.getenv("CLASSIFIER_LLM_MODEL") or os.getenv("LLM_MODEL", "")
    executor_model = os.getenv("EXECUTOR_LLM_MODEL") or os.getenv("LLM_MODEL", "")

    if classifier_model and classifier_model != (os.getenv("LLM_MODEL", "")):
        try:
            coordinator_kwargs["classifier_llm"] = create_llm_from_model(classifier_model, temperature=0.1)
            logger.info(f"分类 Agent 独立模型: {classifier_model}")
        except Exception as e:
            logger.warning(f"分类 Agent 模型创建失败 (使用全局): {e}")

    if executor_model and executor_model != (os.getenv("LLM_MODEL", "")):
        try:
            coordinator_kwargs["executor_llm"] = create_llm_from_model(executor_model)
            logger.info(f"执行 Agent 独立模型: {executor_model}")
        except Exception as e:
            logger.warning(f"执行 Agent 模型创建失败 (使用全局): {e}")

    # 传递 qdrant_retriever 和 reranker
    if qdrant_enabled and qdrant_retriever:
        coordinator_kwargs["qdrant_retriever"] = qdrant_retriever
    if reranker:
        coordinator_kwargs["reranker"] = reranker

    if use_langgraph:
        try:
            from ticket_agent.coordinator.langgraph_workflow import LangGraphCoordinator
            coordinator = LangGraphCoordinator(**coordinator_kwargs)
            logger.info("使用 LangGraph 工作流编排")
        except ImportError:
            logger.warning("langgraph 未安装，回退到线性编排")
            coordinator = LinearCoordinator(**coordinator_kwargs)
    else:
        coordinator = LinearCoordinator(**coordinator_kwargs)

    # 注入到路由
    set_coordinator(coordinator)

    # ── 自动加载已保存的模型配置 ──
    # 如果用户在界面上保存过模型配置，启动时自动应用
    try:
        from ticket_agent.models.config_store import get_model_config_store
        from llm.provider_map import resolve_model
        from llm.factory import create_llm

        config_store = get_model_config_store()
        saved_config = config_store.get_active()
        if saved_config and saved_config.api_key:
            info = resolve_model(saved_config.model)
            saved_llm = create_llm({
                "provider": info.provider,
                "model": saved_config.model,
                "api_key": saved_config.api_key,
                "base_url": saved_config.base_url or info.base_url or "",
            })
            coordinator.llm = saved_llm
            coordinator.classifier.llm = saved_llm
            coordinator.executor.llm = saved_llm
            logger.info(f"已加载保存的模型配置: {saved_config.label} ({saved_config.model})")
    except Exception as e:
        logger.warning(f"自动加载模型配置失败（使用默认模型）: {e}")

    # 飞书集成
    mcp_enabled = os.getenv("MCP_ENABLED", "false").lower() in ("1", "true", "yes")
    if mcp_enabled:
        try:
            from ticket_agent.mcp.server import TicketMCPServer
            from ticket_agent.monitoring.metrics import MCP_SERVER_ACTIVE

            mcp_server = TicketMCPServer(coordinator=coordinator)
            mcp_app = mcp_server.get_fastapi_app()
            if mcp_app:
                app.mount("/mcp", mcp_app)
                MCP_SERVER_ACTIVE.labels(protocol="sse").set(1)
                logger.info("MCP Server 已挂载: /mcp/tools, /mcp/call-tool")
            else:
                logger.warning("MCP SDK 未安装，MCP Server 不可用")
        except Exception as e:
            logger.warning(f"MCP Server 初始化失败: {e}")

    # ── 启动 Embedding Pipeline（生产化） ──
    try:
        from ticket_agent.knowledge.embedding_pipeline import get_embedding_pipeline
        pipeline = get_embedding_pipeline()
        await pipeline.start()
        logger.info("知识库自动 Embedding Pipeline 已启动")
    except Exception as e:
        logger.warning(f"Embedding Pipeline 启动失败: {e}")

    # ── 启动调度服务 ──
    try:
        from ticket_agent.scheduler.scheduler_service import SchedulerService
        scheduler = SchedulerService()
        await scheduler.start()
        logger.info("调度服务已启动 (间隔=5s)")
    except Exception as e:
        logger.warning(f"调度服务启动失败: {e}")

    # ── 初始化进化执行器 ──
    try:
        from ticket_agent.evolution.executor import EvolutionExecutor
        from ticket_agent.api.deps import set_evolution_executor
        evolution_executor = EvolutionExecutor(llm=llm)
        set_evolution_executor(evolution_executor)
        logger.info("进化执行器已就绪")
    except Exception as e:
        logger.warning(f"进化执行器初始化失败: {e}")

    # 飞书集成
    if FEISHU_AVAILABLE and feishu_router is not None:
        set_feishu_bot_coordinator(coordinator)
        app.include_router(feishu_router)
        from ticket_agent.integrations.feishu.config import get_config as get_feishu_cfg
        if get_feishu_cfg().enabled:
            logger.info("飞书集成已启用，等待飞书事件回调")
        else:
            logger.info("飞书集成已注册（未配置 FEISHU_APP_ID/FEISHU_APP_SECRET，需设置环境变量启用）")

    # 企业微信集成
    if WECOM_AVAILABLE and wecom_router is not None:
        set_wecom_coordinator(coordinator)
        app.include_router(wecom_router)
        from ticket_agent.integrations.wecom.config import get_config as get_wecom_cfg
        if get_wecom_cfg().enabled:
            logger.info("企业微信集成已启用，等待企微回调")
        else:
            logger.info("企业微信集成已注册（未配置 WECOM_CORP_ID/WECOM_AGENT_SECRET，需设置环境变量启用）")

    # 钉钉集成
    if DINGTALK_AVAILABLE and dingtalk_router is not None:
        set_dingtalk_coordinator(coordinator)
        app.include_router(dingtalk_router)
        from ticket_agent.integrations.dingtalk.config import get_config as get_dingtalk_cfg
        if get_dingtalk_cfg().enabled:
            logger.info("钉钉集成已启用，等待钉钉回调")
        else:
            logger.info("钉钉集成已注册（未配置 DINGTALK_APP_KEY/DINGTALK_APP_SECRET，需设置环境变量启用）")

    logger.info(f"Coordinator 初始化完成")
    logger.info(f"LLM: provider={llm.__class__.__name__}, model={getattr(llm, 'model', 'unknown')}")
    logger.info("服务已就绪，访问 http://localhost:8000/docs 查看 API 文档")
    logger.info("=" * 50)

    yield

    # ═══ 优雅关闭 ═══
    logger.info("正在关闭服务...")

    # 1. 关闭 Embedding Pipeline
    try:
        if 'pipeline' in locals():
            await pipeline.stop()
            logger.info("Embedding Pipeline 已关闭")
    except Exception as e:
        logger.warning(f"Embedding Pipeline 关闭异常: {e}")

    # 2. 关闭 MCP 客户端连接
    try:
        if 'mcp_server' in locals() and hasattr(mcp_server, 'close'):
            await mcp_server.close()
            logger.info("MCP 服务已关闭")
    except Exception as e:
        logger.warning(f"MCP 关闭异常: {e}")

    # 3. 关闭调度服务
    try:
        if 'scheduler' in locals():
            await scheduler.stop()
    except Exception as e:
        logger.warning(f"调度服务关闭异常: {e}")

    # 4. 关闭数据库连接
    try:
        from ticket_agent.database import close_db
        close_db()
        logger.info("数据库连接已关闭")
    except Exception as e:
        logger.warning(f"数据库关闭异常: {e}")

    logger.info("服务已完全关闭")


app = FastAPI(
    title="企业工单智能处理 Agent",
    version="1.0.0",
    description="""
    基于 Multi-Agent + RAG 的工单自动化处理系统。

    ## 工作流程
    1. **分类 Agent** - 自动判断工单类别（IT/HR/财务/运维/其他）
    2. **RAG 检索** - 从知识库查找相关解决方案
    3. **执行 Agent** - 自动查询/更新工单状态
    4. **汇总回复** - 生成最终回复

    ## 快速体验
    ```
    POST /ticket
    {"content": "我的电脑蓝屏了，麻烦帮忙看看", "user_id": "zhangsan"}
    ```
    """,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API 速率限制中间件
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    from utils.token_bucket import get_api_bucket

    # 跳过静态文件和健康检查
    path = request.url.path
    if path.startswith(("/static/", "/uploads/", "/docs", "/openapi.json", "/health")):
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    bucket = get_api_bucket(f"api:{client_ip}", rpm=60)
    if not bucket.consume(1):
        return JSONResponse(
            status_code=429,
            content={"detail": "请求过于频繁，请稍后再试"},
            headers={"Retry-After": "60"},
        )
    return await call_next(request)

app.include_router(router, prefix="")
app.include_router(org_router)
app.include_router(auth_router)

# 初始化监控（必须在 mount 之前，否则 middleware 会失败）
if os.getenv("PROMETHEUS_ENABLED", "true").lower() not in ("0", "false", "no", "off"):
    try:
        init_monitoring(app)
        logger.info("Prometheus 监控已初始化: /metrics")
    except Exception as e:
        logger.warning(f"Prometheus 监控初始化失败: {e}")

# Serve uploaded files (多模态支持 — 必须放在主页路由之前)
UPLOAD_DIR = Path(__file__).parent.parent / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# Serve static frontend
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", tags=["前端页面"])
    async def root():
        from fastapi.responses import FileResponse
        return FileResponse(str(STATIC_DIR / "index.html"))
else:
    @app.get("/", tags=["健康检查"])
    async def root():
        return {
            "service": "WorkfloAgent",
            "version": "1.0.0",
            "status": "running",
            "docs": "/docs",
        }


@app.get("/health", tags=["健康检查"])
async def health():
    coordinator = getattr(router, "_coordinator", None)
    return {
        "status": "ok",
        "version": "1.0.0",
        "coordinator_ready": coordinator is not None,
    }
