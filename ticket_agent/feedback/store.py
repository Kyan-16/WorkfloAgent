"""
反馈存储层

基于 SQLAlchemy + SQLite 持久化，支持 CRUD + 统计查询。
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from ticket_agent.database import session_scope
from ticket_agent.database.models import FeedbackRecord

logger = logging.getLogger(__name__)


class TicketFeedback:
    """工单反馈"""

    def __init__(
        self,
        feedback_id: str = "",
        ticket_id: str = "",
        user_id: str = "",
        rating: int = 3,
        feedback_type: str = "neutral",
        comment: str = "",
        resolved: bool = False,
        created_at: str = "",
        updated_at: str = "",
    ):
        self.feedback_id = feedback_id or f"fb_{uuid.uuid4().hex[:8]}"
        self.ticket_id = ticket_id
        self.user_id = user_id
        self.rating = rating
        self.feedback_type = feedback_type
        self.comment = comment
        self.resolved = resolved
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.updated_at = updated_at or self.created_at

    def to_dict(self) -> dict:
        return {
            "feedback_id": self.feedback_id,
            "ticket_id": self.ticket_id,
            "user_id": self.user_id,
            "rating": self.rating,
            "feedback_type": self.feedback_type,
            "comment": self.comment,
            "resolved": self.resolved,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TicketFeedback":
        return cls(**{k: v for k, v in d.items()})


def _record_to_feedback(r: FeedbackRecord) -> TicketFeedback:
    return TicketFeedback(
        feedback_id=r.feedback_id,
        ticket_id=r.ticket_id,
        user_id=r.user_id,
        rating=r.rating,
        feedback_type=r.feedback_type,
        comment=r.comment,
        resolved=r.resolved,
        created_at=r.created_at.isoformat() if r.created_at else "",
        updated_at=r.updated_at.isoformat() if r.updated_at else "",
    )


class FeedbackStore:
    """反馈存储"""

    def __init__(self, db_path: str = ""):
        # db_path kept for backward compatibility, data now in SQLite
        pass

    def add(self, feedback: TicketFeedback) -> TicketFeedback:
        with session_scope() as session:
            record = FeedbackRecord(
                feedback_id=feedback.feedback_id,
                ticket_id=feedback.ticket_id,
                user_id=feedback.user_id,
                rating=feedback.rating,
                feedback_type=feedback.feedback_type,
                comment=feedback.comment,
                resolved=feedback.resolved,
            )
            session.add(record)
        return feedback

    def get(self, feedback_id: str) -> Optional[TicketFeedback]:
        with session_scope() as session:
            r = session.query(FeedbackRecord).filter(
                FeedbackRecord.feedback_id == feedback_id
            ).first()
            return _record_to_feedback(r) if r else None

    def get_by_ticket(self, ticket_id: str) -> Optional[TicketFeedback]:
        with session_scope() as session:
            r = session.query(FeedbackRecord).filter(
                FeedbackRecord.ticket_id == ticket_id
            ).first()
            return _record_to_feedback(r) if r else None

    def list_all(
        self,
        limit: int = 50,
        offset: int = 0,
        feedback_type: Optional[str] = None,
        resolved: Optional[bool] = None,
    ) -> list[TicketFeedback]:
        with session_scope() as session:
            q = session.query(FeedbackRecord)
            if feedback_type:
                q = q.filter(FeedbackRecord.feedback_type == feedback_type)
            if resolved is not None:
                q = q.filter(FeedbackRecord.resolved == resolved)
            q = q.order_by(FeedbackRecord.created_at.desc())
            return [_record_to_feedback(r) for r in q.offset(offset).limit(limit).all()]

    def get_stats(self) -> dict:
        with session_scope() as session:
            from sqlalchemy import func
            total = session.query(func.count(FeedbackRecord.id)).scalar() or 0
            if total == 0:
                return {"total": 0, "avg_rating": 0, "positive": 0, "negative": 0, "neutral": 0}

            avg_rating = session.query(func.avg(FeedbackRecord.rating)).scalar() or 0
            positive = session.query(func.count(FeedbackRecord.id)).filter(
                FeedbackRecord.feedback_type == "positive"
            ).scalar() or 0
            negative = session.query(func.count(FeedbackRecord.id)).filter(
                FeedbackRecord.feedback_type == "negative"
            ).scalar() or 0
            neutral = session.query(func.count(FeedbackRecord.id)).filter(
                FeedbackRecord.feedback_type == "neutral"
            ).scalar() or 0
            unresolved_negative = session.query(func.count(FeedbackRecord.id)).filter(
                FeedbackRecord.feedback_type == "negative",
                FeedbackRecord.resolved == False,
            ).scalar() or 0

            return {
                "total": total,
                "avg_rating": round(float(avg_rating), 2),
                "positive": positive,
                "negative": negative,
                "neutral": neutral,
                "unresolved_negative": unresolved_negative,
            }


# 全局单例
_store: Optional[FeedbackStore] = None


def get_feedback_store() -> FeedbackStore:
    global _store
    if _store is None:
        _store = FeedbackStore()
    return _store


def reset_feedback_store():
    global _store
    _store = None
