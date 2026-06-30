"""
API 请求/响应数据模型

包含工单处理、反馈、模式查询的 Pydantic 模型。
"""
from typing import Optional, List
from pydantic import BaseModel, Field


class TicketRequest(BaseModel):
    """提交工单请求"""
    content: str = Field(..., description="工单内容", min_length=1, max_length=2000)
    user_id: str = Field(default="", description="用户ID")
    session_id: str = Field(default="default", description="会话ID")
    category: str = Field(default="", description="用户指定的部门分类（为空则由AI自动分类）")
    images: list[str] = Field(default=[], description="图片URL列表（先上传后获得）")


class StreamTicketRequest(BaseModel):
    """流式提交工单请求"""
    content: str
    user_id: str = ""
    session_id: str = "default"
    images: list[str] = []


class UploadResponse(BaseModel):
    """文件上传响应"""
    url: str
    filename: str
    size: int
    content_type: str


class AgentStep(BaseModel):
    """Agent 执行步骤"""
    step: str = ""
    elapsed: float = 0
    result: dict = Field(default_factory=dict)


class TicketResponse(BaseModel):
    """工单处理响应"""
    success: bool = True
    ticket_id: str = ""
    category: str = ""
    response: str = ""
    trace_id: str = ""
    elapsed_seconds: float = 0
    agent_steps: List[AgentStep] = Field(default_factory=list)
    auto_resolved: bool = False
    error: Optional[str] = None


class TicketInfoResponse(BaseModel):
    """工单信息查询响应"""
    ticket_id: str = ""
    user_id: str = ""
    content: str = ""
    category: str = ""
    status: str = ""
    assignee: str = ""
    resolution: str = ""
    created_at: str = ""
    updated_at: str = ""
    agent_response: str = ""
    trace_id: str = ""
    sla_deadline: str = ""
    sla_breached: bool = False


class ResolveRequest(BaseModel):
    """标记已解决请求"""
    resolution: str = Field(default="", description="处理说明/解决方案", max_length=5000)


class HistoryResponse(BaseModel):
    """会话历史响应"""
    session_id: str = ""
    messages: list = Field(default_factory=list)
    count: int = 0


# ═══════════════════════════════════════════════════════════
# 反馈相关
# ═══════════════════════════════════════════════════════════

class FeedbackRequest(BaseModel):
    """提交反馈请求"""
    ticket_id: str = Field(..., description="工单ID")
    rating: int = Field(default=3, ge=1, le=5, description="评分 1-5")
    feedback_type: str = Field(default="neutral", description="反馈类型: positive/negative/neutral")
    comment: str = Field(default="", description="评论内容", max_length=500)


class FeedbackResponse(BaseModel):
    """反馈响应"""
    feedback_id: str = ""
    ticket_id: str = ""
    user_id: str = ""
    rating: int = 3
    feedback_type: str = ""
    comment: str = ""
    created_at: str = ""


class FeedbackStatsResponse(BaseModel):
    """反馈统计响应"""
    total: int = 0
    avg_rating: float = 0
    positive: int = 0
    negative: int = 0
    neutral: int = 0
    unresolved_negative: int = 0


# ═══════════════════════════════════════════════════════════
# 模式相关
# ═══════════════════════════════════════════════════════════

class PatternResponse(BaseModel):
    """工单模式响应"""
    pattern_id: str = ""
    category: str = ""
    problem_summary: str = ""
    solution: str = ""
    keywords: List[str] = Field(default_factory=list)
    confidence: float = 0
    frequency: int = 1
    source_tickets: List[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
