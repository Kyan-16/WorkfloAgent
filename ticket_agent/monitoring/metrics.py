"""
Prometheus 自定义指标定义

包含三类指标：
1. 基础 HTTP 指标（由 prometheus-fastapi-instrumentator 自动采集）
2. AI 业务指标（手动埋点）
3. 自进化指标（P2 新增）
"""
from prometheus_client import Counter, Histogram, Gauge

# ═══════════════════════════════════════════════════════════
# 工单处理指标
# ═══════════════════════════════════════════════════════════

# 工单处理耗时（秒），按 category 和 result 分桶
TICKET_PROCESSING_DURATION = Histogram(
    "ticket_processing_duration_seconds",
    "工单处理耗时（秒）",
    labelnames=["category", "result", "coordinator"],
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, float("inf")),
)

# 工单处理计数，按 category、status、是否转人工分
TICKET_PROCESSING_TOTAL = Counter(
    "ticket_processing_total",
    "工单处理总数",
    labelnames=["category", "result", "auto_resolved"],
)

# ═══════════════════════════════════════════════════════════
# Agent 步骤耗时指标
# ═══════════════════════════════════════════════════════════

AGENT_STEP_DURATION = Histogram(
    "agent_step_duration_seconds",
    "Agent 各步骤耗时（秒）",
    labelnames=["step", "category"],
    buckets=(0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, float("inf")),
)

# ═══════════════════════════════════════════════════════════
# 工具调用指标
# ═══════════════════════════════════════════════════════════

TOOL_CALLS_TOTAL = Counter(
    "tool_calls_total",
    "工具调用总数",
    labelnames=["tool", "success"],
)

TOOL_CALL_DURATION = Histogram(
    "tool_call_duration_seconds",
    "工具调用耗时（秒）",
    labelnames=["tool"],
    buckets=(0.05, 0.1, 0.5, 1.0, 2.0, 5.0, float("inf")),
)

# ═══════════════════════════════════════════════════════════
# Token 消耗指标
# ═══════════════════════════════════════════════════════════

LLM_TOKENS_TOTAL = Counter(
    "llm_tokens_total",
    "LLM Token 消耗总数",
    labelnames=["model", "type"],  # type: prompt / completion
)

LLM_REQUEST_DURATION = Histogram(
    "llm_request_duration_seconds",
    "LLM 请求耗时（秒）",
    labelnames=["model"],
    buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, float("inf")),
)

# ═══════════════════════════════════════════════════════════
# RAG 检索指标
# ═══════════════════════════════════════════════════════════

RAG_RETRIEVAL_DURATION = Histogram(
    "rag_retrieval_duration_seconds",
    "RAG 检索耗时（秒）",
    labelnames=["category"],
    buckets=(0.05, 0.1, 0.5, 1.0, 2.0, 5.0, float("inf")),
)

RAG_RETRIEVAL_TOTAL = Counter(
    "rag_retrieval_total",
    "RAG 检索总数",
    labelnames=["category", "has_result"],
)

RAG_ZERO_RESULT_TOTAL = Counter(
    "rag_zero_result_total",
    "RAG 检索零结果数",
    labelnames=["category"],
)

# ═══════════════════════════════════════════════════════════
# 自进化指标（P2 新增）
# ═══════════════════════════════════════════════════════════

EVOLUTION_REVIEW_TOTAL = Counter(
    "evolution_review_total",
    "工单复盘总数",
    labelnames=["category", "result"],
)

EVOLUTION_KNOWLEDGE_GAP_TOTAL = Counter(
    "evolution_knowledge_gap_total",
    "知识缺口发现总数",
    labelnames=["category"],
)

EVOLUTION_PATTERN_TOTAL = Counter(
    "evolution_pattern_total",
    "工单模式提取总数",
    labelnames=["category"],
)

# ═══════════════════════════════════════════════════════════
# 系统 / 存活指标
# ═══════════════════════════════════════════════════════════

AGENT_INFO = Gauge(
    "agent_info",
    "Agent 版本和运行状态信息",
    labelnames=["version"],
)
AGENT_INFO.labels(version="2.0.0").set(1)

# MCP 服务状态
MCP_SERVER_ACTIVE = Gauge(
    "mcp_server_active",
    "MCP Server 是否活跃",
    labelnames=["protocol"],
)
