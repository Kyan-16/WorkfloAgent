"""
工单模式提取器

从已解决的工单中自动提取"问题-方案"模式，沉淀为可复用的知识。
模式持久化使用 SQLAlchemy + SQLite。
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from ticket_agent.database import session_scope
from ticket_agent.database.models import PatternRecord

logger = logging.getLogger(__name__)


class TicketPattern:
    """工单处理模式"""

    def __init__(
        self,
        pattern_id: str = "",
        category: str = "",
        problem_summary: str = "",
        solution: str = "",
        keywords: list[str] = None,
        confidence: float = 0.0,
        source_tickets: list[str] = None,
        frequency: int = 1,
        created_at: str = "",
        updated_at: str = "",
    ):
        self.pattern_id = pattern_id
        self.category = category
        self.problem_summary = problem_summary
        self.solution = solution
        self.keywords = keywords or []
        self.confidence = confidence
        self.source_tickets = source_tickets or []
        self.frequency = frequency
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()
        self.updated_at = updated_at or self.created_at

    def to_dict(self) -> dict:
        return {
            "pattern_id": self.pattern_id,
            "category": self.category,
            "problem_summary": self.problem_summary,
            "solution": self.solution,
            "keywords": self.keywords,
            "confidence": self.confidence,
            "source_tickets": self.source_tickets,
            "frequency": self.frequency,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TicketPattern":
        return cls(**{k: v for k, v in d.items() if k in cls.__init__.__code__.co_varnames})


def _record_to_pattern(r: PatternRecord) -> TicketPattern:
    return TicketPattern(
        pattern_id=r.pattern_id,
        category=r.category,
        problem_summary=r.problem_summary,
        solution=r.solution,
        keywords=json.loads(r.keywords) if r.keywords else [],
        confidence=r.confidence,
        source_tickets=json.loads(r.source_tickets) if r.source_tickets else [],
        frequency=r.frequency,
        created_at=r.created_at.isoformat() if r.created_at else "",
        updated_at=r.updated_at.isoformat() if r.updated_at else "",
    )


class PatternStore:
    """模式持久化存储 (SQLite)"""

    def __init__(self, db_path: str = ""):
        pass

    def save(self, pattern: TicketPattern):
        with session_scope() as session:
            existing = session.query(PatternRecord).filter(
                PatternRecord.pattern_id == pattern.pattern_id
            ).first()
            if existing:
                existing.category = pattern.category
                existing.problem_summary = pattern.problem_summary
                existing.solution = pattern.solution
                existing.keywords = json.dumps(pattern.keywords, ensure_ascii=False)
                existing.confidence = pattern.confidence
                existing.source_tickets = json.dumps(pattern.source_tickets, ensure_ascii=False)
                existing.frequency = pattern.frequency
            else:
                session.add(PatternRecord(
                    pattern_id=pattern.pattern_id,
                    category=pattern.category,
                    problem_summary=pattern.problem_summary,
                    solution=pattern.solution,
                    keywords=json.dumps(pattern.keywords, ensure_ascii=False),
                    confidence=pattern.confidence,
                    source_tickets=json.dumps(pattern.source_tickets, ensure_ascii=False),
                    frequency=pattern.frequency,
                ))

    def search(self, category: str, keywords: list[str], top_k: int = 3) -> list[TicketPattern]:
        """按分类和关键词搜索匹配的模式"""
        raw = []
        with session_scope() as session:
            records = session.query(PatternRecord).filter(
                PatternRecord.category == category
            ).all()
            raw = [(r.keywords, r.confidence, r.frequency,
                    r.pattern_id, r.category, r.problem_summary, r.solution,
                    r.source_tickets, r.created_at, r.updated_at) for r in records]

        if not raw:
            return []

        kw_lower = [k.lower() for k in keywords]
        scored = []
        for kw_str, conf, freq, pid, cat, prob, sol, src, ca, ua in raw:
            pk = json.loads(kw_str) if kw_str else []
            score = sum(1 for k in pk if k.lower() in kw_lower)
            if score > 0:
                p = TicketPattern(pattern_id=pid, category=cat, problem_summary=prob, solution=sol,
                                  keywords=pk, confidence=conf, source_tickets=json.loads(src) if src else [],
                                  frequency=freq, created_at=ca, updated_at=ua)
                scored.append((score * conf * (1 + 0.1 * freq), p))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:top_k]]

    def get_all(self, category: Optional[str] = None) -> list[TicketPattern]:
        with session_scope() as session:
            q = session.query(PatternRecord)
            if category:
                q = q.filter(PatternRecord.category == category)
            return [_record_to_pattern(r) for r in q.all()]

    def delete(self, pattern_id: str) -> bool:
        with session_scope() as session:
            r = session.query(PatternRecord).filter(
                PatternRecord.pattern_id == pattern_id
            ).first()
            if r:
                session.delete(r)
                return True
        return False

    @property
    def count(self) -> int:
        with session_scope() as session:
            from sqlalchemy import func
            return session.query(func.count(PatternRecord.id)).scalar() or 0


_pattern_store: Optional[PatternStore] = None


def get_pattern_store() -> PatternStore:
    global _pattern_store
    if _pattern_store is None:
        _pattern_store = PatternStore()
    return _pattern_store


def reset_pattern_store():
    global _pattern_store
    _pattern_store = None


class PatternExtractor:
    """工单模式提取器"""

    def __init__(self, llm=None):
        self.llm = llm
        self.store = get_pattern_store()

    async def extract(self, ticket_data: dict) -> Optional[TicketPattern]:
        category = ticket_data.get("category", "")
        content = ticket_data.get("content", "")
        solution = ticket_data.get("solution", "")
        if not category or not content or not solution:
            return None
        if self.llm:
            return await self._extract_with_llm(ticket_data)
        return self._extract_lightweight(ticket_data)

    async def _extract_with_llm(self, ticket_data: dict) -> Optional[TicketPattern]:
        from llm.base import ChatMessage
        prompt = f"""请从以下工单中提取可复用的"问题-方案"模式。

工单分类：{ticket_data.get("category", "")}
用户问题：{ticket_data.get("content", "")}
解决方案：{ticket_data.get("solution", "")}

请输出 JSON 格式（不要额外文字）：
{{
  "problem_summary": "问题的通用描述（20字内）",
  "solution": "通用的解决方案步骤（50字内）",
  "keywords": ["关键词1", "关键词2", "关键词3"],
  "confidence": 0.0-1.0
}}"""
        try:
            resp = await self.llm.generate([ChatMessage(role="user", content=prompt)])
            content = resp.content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            result = json.loads(content)
            existing = self.store.search(
                ticket_data.get("category", ""), result.get("keywords", []), top_k=1,
            )
            if existing and existing[0].confidence > 0.8:
                p = existing[0]
                p.frequency += 1
                if ticket_data.get("ticket_id") not in p.source_tickets:
                    p.source_tickets.append(ticket_data["ticket_id"])
                p.updated_at = datetime.now(timezone.utc).isoformat()
                self.store.save(p)
                return p
            pattern = TicketPattern(
                pattern_id=f"pat_{uuid.uuid4().hex[:8]}",
                category=ticket_data.get("category", ""),
                problem_summary=result.get("problem_summary", ""),
                solution=result.get("solution", ""),
                keywords=result.get("keywords", []),
                confidence=result.get("confidence", 0.5),
                source_tickets=[ticket_data.get("ticket_id", "")],
                frequency=1,
            )
            self.store.save(pattern)
            return pattern
        except Exception as e:
            logger.warning(f"LLM 模式提取失败: {e}")
            return self._extract_lightweight(ticket_data)

    def _extract_lightweight(self, ticket_data: dict) -> Optional[TicketPattern]:
        import re
        content = ticket_data.get("content", "")
        solution = ticket_data.get("solution", "")
        words = re.findall(r"[一-鿿\w]+", content)
        stop_words = {"我", "的", "了", "是", "在", "有", "和", "就", "不", "也", "都", "要", "这个", "那个"}
        keywords = list(set(w for w in words if len(w) > 1 and w not in stop_words))[:5]
        pattern = TicketPattern(
            pattern_id=f"pat_{uuid.uuid4().hex[:8]}",
            category=ticket_data.get("category", ""),
            problem_summary=content[:30] if content else "",
            solution=solution[:50] if solution else "",
            keywords=keywords,
            confidence=0.3,
            source_tickets=[ticket_data.get("ticket_id", "")],
            frequency=1,
        )
        self.store.save(pattern)
        return pattern

    def find_matching_patterns(self, category: str, user_input: str, max_results: int = 3) -> list[dict]:
        import re
        words = re.findall(r"[一-鿿\w]+", user_input)
        stop_words = {"我", "的", "了", "是", "在", "有", "和", "就", "不", "也", "都", "要", "这个", "那个"}
        keywords = list(set(w for w in words if len(w) > 1 and w not in stop_words))
        patterns = self.store.search(category, keywords, top_k=max_results)
        return [p.to_dict() for p in patterns]
