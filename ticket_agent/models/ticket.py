"""
工单数据模型
"""
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class TicketStatus(str, Enum):
    PENDING = "待处理"
    PROCESSING = "处理中"
    AWAITING_CONFIRM = "待确认"   # AI 自动处理后，等用户确认
    RESOLVED = "已解决"
    CLOSED = "已关闭"
    ESCALATED = "已转人工"


class TicketCategory(str, Enum):
    IT = "IT"
    HR = "HR"
    FINANCE = "财务"
    OPS = "运维"
    OTHER = "其他"


class Ticket:
    """工单实体"""

    def __init__(
        self,
        content: str,
        user_id: str = "",
        category: Optional[TicketCategory] = None,
        ticket_id: Optional[str] = None,
        status: TicketStatus = TicketStatus.PENDING,
        session_id: str = "default",
        assignee: str = "",
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
        agent_response: str = "",
        trace_id: str = "",
        **kwargs,
    ):
        self.ticket_id = ticket_id or f"TK-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        self.user_id = user_id
        self.content = content
        self.category = category
        self.status = status
        self.session_id = session_id
        self.assignee = assignee
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.updated_at = updated_at or self.created_at
        self.agent_response = agent_response
        self.trace_id = trace_id

    def to_dict(self) -> dict:
        return {
            "ticket_id": self.ticket_id,
            "user_id": self.user_id,
            "content": self.content,
            "category": self.category.value if self.category else None,
            "status": self.status.value if self.status else "待处理",
            "session_id": self.session_id,
            "assignee": self.assignee,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "agent_response": self.agent_response,
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Ticket":
        category_str = data.get("category")
        category = TicketCategory(category_str) if category_str and category_str in [c.value for c in TicketCategory] else None
        status_str = data.get("status", "待处理")
        status = TicketStatus(status_str) if status_str in [s.value for s in TicketStatus] else TicketStatus.PENDING
        return cls(
            ticket_id=data.get("ticket_id", ""),
            user_id=data.get("user_id", ""),
            content=data.get("content", ""),
            category=category,
            status=status,
            session_id=data.get("session_id", "default"),
            assignee=data.get("assignee", ""),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            agent_response=data.get("agent_response", ""),
            trace_id=data.get("trace_id", ""),
        )
