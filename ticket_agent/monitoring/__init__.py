"""监控模块 —— Prometheus 指标采集"""
import os
import logging

from prometheus_fastapi_instrumentator import Instrumentator

from ticket_agent.monitoring.metrics import (
    TICKET_PROCESSING_DURATION,
    TICKET_PROCESSING_TOTAL,
    AGENT_STEP_DURATION,
    TOOL_CALLS_TOTAL,
    TOOL_CALL_DURATION,
    LLM_TOKENS_TOTAL,
    LLM_REQUEST_DURATION,
    RAG_RETRIEVAL_DURATION,
    RAG_RETRIEVAL_TOTAL,
    RAG_ZERO_RESULT_TOTAL,
    EVOLUTION_REVIEW_TOTAL,
    EVOLUTION_KNOWLEDGE_GAP_TOTAL,
    EVOLUTION_PATTERN_TOTAL,
    MCP_SERVER_ACTIVE,
)

logger = logging.getLogger(__name__)


def init_monitoring(app):
    """初始化 Prometheus 监控"""
    if os.getenv("PROMETHEUS_ENABLED", "true").lower() in ("0", "false", "no", "off"):
        logger.info("Prometheus 监控未启用（PROMETHEUS_ENABLED=false）")
        return

    # 使用 should_group_status_codes=False 避免路由兼容问题
    try:
        Instrumentator(should_group_status_codes=False).instrument(app).expose(app, endpoint="/metrics")
        logger.info("Prometheus 监控已初始化: /metrics")
    except Exception as e:
        logger.warning(f"Prometheus 监控初始化失败: {e}")
