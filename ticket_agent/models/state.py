"""
LangGraph 状态定义
"""
from typing import TypedDict, List, Optional, Dict, Any


class TicketState(TypedDict, total=False):
    """工单 Agent 工作流状态"""

    # 输入
    user_input: str
    session_id: str
    user_id: str

    # 分类阶段
    category: str
    confidence: float
    needs_human: bool
    classification_reason: str

    # RAG 阶段
    retrieved_docs: List[Dict[str, Any]]
    rag_context: str

    # 执行阶段
    tool_calls: List[Dict[str, Any]]
    tool_results: List[Dict[str, Any]]

    # 输出
    final_response: str
    trace_id: str

    # 流程控制
    error: Optional[str]
    retry_count: int
