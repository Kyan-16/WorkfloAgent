"""
工单复盘器 (TicketReviewer)

在工单处理完成后自动复盘，评估处理质量并输出改进建议。
复盘数据使用 SQLAlchemy + SQLite 持久化。
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from ticket_agent.database import session_scope
from ticket_agent.database.models import ReviewRecord

logger = logging.getLogger(__name__)


class TicketReview:
    """单次工单复盘记录"""

    def __init__(
        self,
        review_id: str = "",
        ticket_id: str = "",
        category: str = "",
        classification_score: float = 0.0,
        rag_hit_rate: float = 0.0,
        response_quality: float = 0.0,
        overall_score: float = 0.0,
        suggestions: list[str] = None,
        follow_up_needed: bool = False,
        created_at: str = "",
    ):
        self.review_id = review_id or f"rv_{uuid.uuid4().hex[:8]}"
        self.ticket_id = ticket_id
        self.category = category
        self.classification_score = classification_score
        self.rag_hit_rate = rag_hit_rate
        self.response_quality = response_quality
        self.overall_score = overall_score
        self.suggestions = suggestions or []
        self.follow_up_needed = follow_up_needed
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "review_id": self.review_id,
            "ticket_id": self.ticket_id,
            "category": self.category,
            "classification_score": self.classification_score,
            "rag_hit_rate": self.rag_hit_rate,
            "response_quality": self.response_quality,
            "overall_score": self.overall_score,
            "suggestions": self.suggestions,
            "follow_up_needed": self.follow_up_needed,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TicketReview":
        return cls(**{k: v for k, v in d.items()})


def _record_to_review(r: ReviewRecord) -> TicketReview:
    return TicketReview(
        review_id=r.review_id,
        ticket_id=r.ticket_id,
        category=r.category,
        classification_score=r.classification_score,
        rag_hit_rate=r.rag_hit_rate,
        response_quality=r.response_quality,
        overall_score=r.overall_score,
        suggestions=json.loads(r.suggestions) if r.suggestions else [],
        follow_up_needed=r.follow_up_needed or False,
        created_at=r.created_at.isoformat() if r.created_at else "",
    )


class ReviewStore:
    """复盘结果持久化存储 (SQLite)"""

    def __init__(self, db_path: str = ""):
        pass

    def save(self, review: TicketReview):
        with session_scope() as session:
            existing = session.query(ReviewRecord).filter(
                ReviewRecord.review_id == review.review_id
            ).first()
            if existing:
                existing.overall_score = review.overall_score
                existing.classification_score = review.classification_score
                existing.rag_hit_rate = review.rag_hit_rate
                existing.response_quality = review.response_quality
                existing.suggestions = json.dumps(review.suggestions, ensure_ascii=False)
                existing.follow_up_needed = review.follow_up_needed
            else:
                session.add(ReviewRecord(
                    review_id=review.review_id,
                    ticket_id=review.ticket_id,
                    category=review.category,
                    classification_score=review.classification_score,
                    rag_hit_rate=review.rag_hit_rate,
                    response_quality=review.response_quality,
                    overall_score=review.overall_score,
                    suggestions=json.dumps(review.suggestions, ensure_ascii=False),
                    follow_up_needed=review.follow_up_needed,
                ))

    def list_all(self, limit: int = 50, offset: int = 0) -> list[TicketReview]:
        with session_scope() as session:
            records = session.query(ReviewRecord).order_by(
                ReviewRecord.created_at.desc()
            ).offset(offset).limit(limit).all()
            return [_record_to_review(r) for r in records]

    def get_stats(self) -> dict:
        with session_scope() as session:
            from sqlalchemy import func
            total = session.query(func.count(ReviewRecord.id)).scalar() or 0
            if total == 0:
                return {"total": 0, "avg_overall": 0, "follow_up_needed": 0}
            avg_overall = session.query(func.avg(ReviewRecord.overall_score)).scalar() or 0
            avg_cls = session.query(func.avg(ReviewRecord.classification_score)).scalar() or 0
            avg_rag = session.query(func.avg(ReviewRecord.rag_hit_rate)).scalar() or 0
            avg_resp = session.query(func.avg(ReviewRecord.response_quality)).scalar() or 0
            follow_up = session.query(func.count(ReviewRecord.id)).filter(
                ReviewRecord.follow_up_needed == True
            ).scalar() or 0
            return {
                "total": total,
                "avg_overall": round(float(avg_overall), 2),
                "avg_classification": round(float(avg_cls), 2),
                "avg_rag_hit": round(float(avg_rag), 2),
                "avg_response_quality": round(float(avg_resp), 2),
                "follow_up_needed": follow_up,
            }


_store: Optional[ReviewStore] = None


def get_review_store() -> ReviewStore:
    global _store
    if _store is None:
        _store = ReviewStore()
    return _store


def reset_review_store():
    global _store
    _store = None


class TicketReviewer:
    """工单复盘器"""

    def __init__(self, llm=None):
        self.llm = llm
        self.store = get_review_store()

    async def review_ticket(self, ticket_data: dict) -> TicketReview:
        rag_docs = ticket_data.get("rag_doc_count", 0)
        rag_hit = 1.0 if rag_docs > 0 else 0.0
        has_tool_calls = bool(ticket_data.get("tool_calls"))
        if self.llm:
            return await self._review_with_llm(ticket_data, rag_hit, has_tool_calls)
        return self._review_rule_based(ticket_data, rag_hit, has_tool_calls)

    async def _review_with_llm(self, ticket_data: dict, rag_hit: float, has_tool_calls: bool) -> TicketReview:
        from llm.base import ChatMessage
        prompt = f"""请对这次工单处理进行复盘评估，输出 JSON 格式（不要额外文字）。

工单分类：{ticket_data.get("category", "")}
用户问题：{ticket_data.get("content", "")}
Agent 回复：{ticket_data.get("response", "")}
RAG 检索到文档数：{ticket_data.get("rag_doc_count", 0)}
是否调用了工具：{has_tool_calls}

评估维度（0.0-1.0）：
1. classification_score: 工单分类是否准确
2. response_quality: 回复是否解决了用户问题
3. overall_score: 综合评分

输出：
{{
  "classification_score": 0.0-1.0,
  "response_quality": 0.0-1.0,
  "overall_score": 0.0-1.0,
  "suggestions": ["改进建议1", "改进建议2"],
  "follow_up_needed": true/false
}}"""
        try:
            resp = await self.llm.generate([ChatMessage(role="user", content=prompt)])
            content = resp.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            result = json.loads(content)
            review = TicketReview(
                ticket_id=ticket_data.get("ticket_id", ""),
                category=ticket_data.get("category", ""),
                classification_score=result.get("classification_score", 0.5),
                rag_hit_rate=rag_hit,
                response_quality=result.get("response_quality", 0.5),
                overall_score=result.get("overall_score", 0.5),
                suggestions=result.get("suggestions", []),
                follow_up_needed=result.get("follow_up_needed", False),
            )
            self.store.save(review)
            return review
        except Exception as e:
            logger.warning(f"LLM 复盘失败: {e}")
            return self._review_rule_based(ticket_data, rag_hit, has_tool_calls)

    def _review_rule_based(self, ticket_data: dict, rag_hit: float, has_tool_calls: bool) -> TicketReview:
        rag_docs = ticket_data.get("rag_doc_count", 0)
        cls_score = 0.7 if rag_docs > 0 else 0.5
        resp_quality = min(0.6 + (0.2 if has_tool_calls else 0.0) + (0.1 if rag_docs > 0 else 0.0), 1.0)
        overall = (cls_score + rag_hit + resp_quality) / 3
        suggestions = []
        if rag_docs == 0:
            suggestions.append(f"知识库缺少相关文档，建议补充 [{ticket_data.get('category', '')}] 类内容")
        review = TicketReview(
            ticket_id=ticket_data.get("ticket_id", ""),
            category=ticket_data.get("category", ""),
            classification_score=round(cls_score, 2),
            rag_hit_rate=rag_hit,
            response_quality=round(resp_quality, 2),
            overall_score=round(overall, 2),
            suggestions=suggestions,
            follow_up_needed=rag_docs == 0,
        )
        self.store.save(review)
        return review

    async def batch_review_recent(self, tickets: list[dict]):
        for t in tickets:
            try:
                await self.review_ticket(t)
            except Exception as e:
                logger.warning(f"批量复盘失败 ticket={t.get('ticket_id')}: {e}")
