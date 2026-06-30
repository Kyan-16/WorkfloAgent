"""
分类准确率追踪器 (AccuracyTracker)

当人类纠正了 Agent 的分类结果时，记录纠正信息。
数据使用 SQLAlchemy + SQLite 持久化。
"""
import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from ticket_agent.database import session_scope
from ticket_agent.database.models import AccuracyRecord

logger = logging.getLogger(__name__)


class ClassificationRecord:
    """单次分类记录"""

    def __init__(
        self,
        record_id: str = "",
        ticket_id: str = "",
        agent_category: str = "",
        human_category: str = "",
        correct: bool = True,
        confidence: float = 0.0,
        created_at: str = "",
    ):
        self.record_id = record_id or f"cr_{uuid.uuid4().hex[:8]}"
        self.ticket_id = ticket_id
        self.agent_category = agent_category
        self.human_category = human_category
        self.correct = correct
        self.confidence = confidence
        self.created_at = created_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "ticket_id": self.ticket_id,
            "agent_category": self.agent_category,
            "human_category": self.human_category,
            "correct": self.correct,
            "confidence": self.confidence,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ClassificationRecord":
        return cls(**{k: v for k, v in d.items()})


def _record_to_accuracy(r: AccuracyRecord) -> ClassificationRecord:
    return ClassificationRecord(
        record_id=r.record_id,
        ticket_id=r.ticket_id,
        agent_category=r.agent_category,
        human_category=r.human_category,
        correct=r.correct or False,
        confidence=r.confidence,
        created_at=r.created_at.isoformat() if r.created_at else "",
    )


class AccuracyStore:
    """准确率数据持久化 (SQLite)"""

    def __init__(self, db_path: str = ""):
        pass

    def save(self, record: ClassificationRecord):
        with session_scope() as session:
            session.add(AccuracyRecord(
                record_id=record.record_id,
                ticket_id=record.ticket_id,
                agent_category=record.agent_category,
                human_category=record.human_category,
                correct=record.correct,
                confidence=record.confidence,
            ))

    def get_stats(self) -> dict:
        with session_scope() as session:
            rows = session.query(
                AccuracyRecord.agent_category,
                AccuracyRecord.human_category,
                AccuracyRecord.correct,
            ).all()

        if not rows:
            return {}

        by_category = defaultdict(list)
        for agent_cat, human_cat, correct in rows:
            by_category[agent_cat].append((human_cat, correct))

        stats = {}
        for cat, recs in by_category.items():
            total = len(recs)
            correct_count = sum(1 for _, c in recs if c)
            stats[cat] = {
                "total": total,
                "correct": correct_count,
                "wrong": total - correct_count,
                "accuracy": round(correct_count / total, 3) if total > 0 else 0,
            }

        total_all = len(rows)
        correct_all = sum(1 for _, _, c in rows if c)
        stats["_overall"] = {
            "total": total_all,
            "correct": correct_all,
            "wrong": total_all - correct_all,
            "accuracy": round(correct_all / total_all, 3) if total_all > 0 else 0,
        }

        confusion = defaultdict(lambda: defaultdict(int))
        for agent_cat, human_cat, correct in rows:
            if not correct:
                confusion[agent_cat][human_cat] += 1
        stats["_confusion"] = {a: dict(h) for a, h in confusion.items()}

        return stats


_store: Optional[AccuracyStore] = None


def get_accuracy_store() -> AccuracyStore:
    global _store
    if _store is None:
        _store = AccuracyStore()
    return _store


def reset_accuracy_store():
    global _store
    _store = None


class AccuracyTracker:
    """分类准确率追踪器"""

    def __init__(self):
        self.store = get_accuracy_store()

    def record_correction(self, ticket_id: str, agent_category: str, human_category: str, confidence: float = 0.0):
        correct = agent_category == human_category
        record = ClassificationRecord(
            ticket_id=ticket_id,
            agent_category=agent_category,
            human_category=human_category,
            correct=correct,
            confidence=confidence,
        )
        self.store.save(record)
        if not correct:
            logger.info(f"分类纠正: {ticket_id} Agent={agent_category} → Human={human_category}")
        return record

    def get_category_accuracy(self, category: str) -> dict:
        stats = self.store.get_stats()
        return stats.get(category, {"total": 0, "accuracy": 0})

    def get_overall_accuracy(self) -> dict:
        stats = self.store.get_stats()
        return stats.get("_overall", {"total": 0, "accuracy": 0})

    def get_confusion_pairs(self) -> list[dict]:
        stats = self.store.get_stats()
        confusion = stats.get("_confusion", {})
        pairs = []
        for agent_cat, human_map in confusion.items():
            for human_cat, count in human_map.items():
                pairs.append({"agent_category": agent_cat, "human_category": human_cat, "count": count})
        pairs.sort(key=lambda x: x["count"], reverse=True)
        return pairs
