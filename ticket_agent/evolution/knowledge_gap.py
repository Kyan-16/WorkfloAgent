"""
知识缺口检测器 (KnowledgeGapDetector)

自动发现知识库中的内容缺口，数据使用 SQLAlchemy + SQLite 持久化。
"""
import json
import logging
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from ticket_agent.database import session_scope
from ticket_agent.database.models import KnowledgeGapRecord

logger = logging.getLogger(__name__)


class KnowledgeGap:
    """知识缺口记录"""

    def __init__(
        self,
        gap_id: str = "",
        category: str = "",
        source_tickets: list[str] = None,
        suggested_title: str = "",
        suggested_content: str = "",
        keywords: list[str] = None,
        frequency: int = 1,
        resolved: bool = False,
        created_at: str = "",
        updated_at: str = "",
    ):
        self.gap_id = gap_id or f"gap_{uuid.uuid4().hex[:8]}"
        self.category = category
        self.source_tickets = source_tickets or []
        self.suggested_title = suggested_title
        self.suggested_content = suggested_content
        self.keywords = keywords or []
        self.frequency = frequency
        self.resolved = resolved
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.updated_at = updated_at or self.created_at

    def to_dict(self) -> dict:
        return {
            "gap_id": self.gap_id,
            "category": self.category,
            "source_tickets": self.source_tickets,
            "suggested_title": self.suggested_title,
            "suggested_content": self.suggested_content,
            "keywords": self.keywords,
            "frequency": self.frequency,
            "resolved": self.resolved,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "KnowledgeGap":
        return cls(**{k: v for k, v in d.items()})


def _record_to_gap(r: KnowledgeGapRecord) -> KnowledgeGap:
    return KnowledgeGap(
        gap_id=r.gap_id,
        category=r.category,
        source_tickets=json.loads(r.source_tickets) if r.source_tickets else [],
        suggested_title=r.suggested_title or "",
        suggested_content=r.suggested_content or "",
        keywords=json.loads(r.keywords) if r.keywords else [],
        frequency=r.frequency or 0,
        resolved=r.resolved or False,
        created_at=r.created_at.isoformat() if r.created_at else "",
        updated_at=r.updated_at.isoformat() if r.updated_at else "",
    )


class GapStore:
    """缺口数据持久化 (SQLite)"""

    def __init__(self, db_path: str = ""):
        pass

    def save(self, gap: KnowledgeGap):
        with session_scope() as session:
            existing = session.query(KnowledgeGapRecord).filter(
                KnowledgeGapRecord.gap_id == gap.gap_id
            ).first()
            if existing:
                existing.category = gap.category
                existing.source_tickets = json.dumps(gap.source_tickets, ensure_ascii=False)
                existing.suggested_title = gap.suggested_title
                existing.suggested_content = gap.suggested_content
                existing.keywords = json.dumps(gap.keywords, ensure_ascii=False)
                existing.frequency = gap.frequency
                existing.resolved = gap.resolved
            else:
                session.add(KnowledgeGapRecord(
                    gap_id=gap.gap_id,
                    category=gap.category,
                    source_tickets=json.dumps(gap.source_tickets, ensure_ascii=False),
                    suggested_title=gap.suggested_title,
                    suggested_content=gap.suggested_content,
                    keywords=json.dumps(gap.keywords, ensure_ascii=False),
                    frequency=gap.frequency,
                    resolved=gap.resolved,
                ))

    def list_unresolved(self, category: Optional[str] = None) -> list[KnowledgeGap]:
        with session_scope() as session:
            q = session.query(KnowledgeGapRecord).filter(
                KnowledgeGapRecord.resolved == False
            )
            if category:
                q = q.filter(KnowledgeGapRecord.category == category)
            q = q.order_by(KnowledgeGapRecord.frequency.desc())
            return [_record_to_gap(r) for r in q.all()]

    def list_all(self, limit: int = 50) -> list[KnowledgeGap]:
        with session_scope() as session:
            records = session.query(KnowledgeGapRecord).order_by(
                KnowledgeGapRecord.frequency.desc()
            ).limit(limit).all()
            return [_record_to_gap(r) for r in records]

    def mark_resolved(self, gap_id: str) -> bool:
        with session_scope() as session:
            r = session.query(KnowledgeGapRecord).filter(
                KnowledgeGapRecord.gap_id == gap_id
            ).first()
            if r:
                r.resolved = True
                return True
        return False

    def get_stats(self) -> dict:
        with session_scope() as session:
            from sqlalchemy import func
            total = session.query(func.count(KnowledgeGapRecord.id)).scalar() or 0
            unresolved = session.query(func.count(KnowledgeGapRecord.id)).filter(
                KnowledgeGapRecord.resolved == False
            ).scalar() or 0
            return {"total": total, "unresolved": unresolved}


_store: Optional[GapStore] = None


def get_gap_store() -> GapStore:
    global _store
    if _store is None:
        _store = GapStore()
    return _store


def reset_gap_store():
    global _store
    _store = None


class KnowledgeGapDetector:
    """知识缺口检测器"""

    def __init__(self, llm=None):
        self.llm = llm
        self.store = get_gap_store()

    async def detect_gap(self, ticket_data: dict) -> Optional[KnowledgeGap]:
        rag_docs = ticket_data.get("rag_doc_count", 0)
        if rag_docs > 0:
            return None
        category = ticket_data.get("category", "")
        content = ticket_data.get("content", "")
        ticket_id = ticket_data.get("ticket_id", "")
        if not category or not content:
            return None

        words = re.findall(r"[一-鿿\w]+", content)
        stop_words = {"我", "的", "了", "是", "在", "有", "和", "就", "不", "也", "都", "要"}
        keywords = list(set(w for w in words if len(w) > 1 and w not in stop_words))[:5]

        suggested_title = ""
        suggested_content = ""
        if self.llm:
            try:
                from llm.base import ChatMessage
                prompt = f"""知识库中缺少关于以下问题的文档，请生成一篇知识库文档草稿。

工单分类：{category}
用户问题：{content}

输出 JSON：
{{
  "title": "文档标题（概括问题领域）",
  "content": "文档内容（包含排查步骤或解决方案，50-100字）"
}}"""
                resp = await self.llm.generate([ChatMessage(role="user", content=prompt)])
                resp_text = resp.content.strip()
                if "```json" in resp_text:
                    resp_text = resp_text.split("```json")[1].split("```")[0].strip()
                elif "```" in resp_text:
                    resp_text = resp_text.split("```")[1].split("```")[0].strip()
                result = json.loads(resp_text)
                suggested_title = result.get("title", "")
                suggested_content = result.get("content", "")
            except Exception as e:
                logger.warning(f"LLM 生成知识库草稿失败: {e}")

        existing = self._find_similar(category, keywords)
        if existing:
            existing.frequency += 1
            if ticket_id not in existing.source_tickets:
                existing.source_tickets.append(ticket_id)
            existing.updated_at = datetime.now(timezone.utc).isoformat()
            self.store.save(existing)
            return existing

        gap = KnowledgeGap(
            category=category,
            source_tickets=[ticket_id],
            suggested_title=suggested_title or f"[{category}] 待补充文档",
            suggested_content=suggested_content,
            keywords=keywords,
            frequency=1,
        )
        self.store.save(gap)
        return gap

    def _find_similar(self, category: str, keywords: list[str]) -> Optional[KnowledgeGap]:
        kw_set = set(k.lower() for k in keywords)
        for gap in self.store.list_unresolved(category):
            if not gap.keywords:
                continue
            gap_kw = set(k.lower() for k in gap.keywords)
            overlap = len(kw_set & gap_kw)
            if overlap >= 2 or (len(kw_set) > 0 and overlap / len(kw_set) > 0.3):
                return gap
        return None

    def get_suggestions(self, category: Optional[str] = None) -> list[dict]:
        gaps = self.store.list_unresolved(category)
        return [{
            "gap_id": g.gap_id,
            "category": g.category,
            "title": g.suggested_title,
            "content": g.suggested_content,
            "keywords": g.keywords,
            "frequency": g.frequency,
            "source_tickets": g.source_tickets,
        } for g in gaps]
