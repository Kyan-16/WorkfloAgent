"""
知识库持久化存储

基于 JSON 文件持久化，支持 CRUD 操作。
初始化时自动加载种子数据，后续增删改直接持久化到文件。
"""
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from ticket_agent.knowledge.seed_data import KNOWLEDGE_BY_CATEGORY as SEED_DATA


class KnowledgeStore:
    """知识库存储（线程安全 JSON 文件 + 内存双写）"""

    def __init__(self, db_path: str = "data/knowledge.json"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._docs: list[dict] = []
        self._version = 0
        self._load_or_init()

    @property
    def version(self) -> int:
        return self._version

    def _load_or_init(self):
        """加载已有数据，或从种子数据初始化"""
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        if os.path.exists(self.db_path) and os.path.getsize(self.db_path) > 0:
            with open(self.db_path, "r", encoding="utf-8") as f:
                self._docs = json.load(f)
        else:
            # 从种子数据初始化
            for category, docs in SEED_DATA.items():
                for doc in docs:
                    meta = doc.get("metadata", {})
                    self._docs.append({
                        "doc_id": meta.get("doc_id", f"{category.lower()}_{uuid.uuid4().hex[:6]}"),
                        "content": doc["content"],
                        "category": category,
                        "source": meta.get("source", "内置文档"),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    })
            self._flush()

    def _flush(self):
        """写入磁盘 + 版本递增"""
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(self._docs, f, ensure_ascii=False, indent=2)
        self._version += 1

    def list_docs(self, category: Optional[str] = None) -> List[dict]:
        """获取文档列表，可按分类过滤"""
        with self._lock:
            if category:
                return [d for d in self._docs if d["category"] == category]
            return list(self._docs)

    def get_doc(self, doc_id: str) -> Optional[dict]:
        """获取单篇文档"""
        with self._lock:
            for d in self._docs:
                if d["doc_id"] == doc_id:
                    return dict(d)
        return None

    def add_doc(self, content: str, category: str, source: str = "用户上传") -> dict:
        """添加文档"""
        doc = {
            "doc_id": f"kb_{uuid.uuid4().hex[:8]}",
            "content": content,
            "category": category,
            "source": source,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._docs.append(doc)
            self._flush()
        return doc

    def update_doc(self, doc_id: str, content: Optional[str] = None,
                   category: Optional[str] = None, source: Optional[str] = None) -> Optional[dict]:
        """更新文档"""
        with self._lock:
            for d in self._docs:
                if d["doc_id"] == doc_id:
                    if content is not None:
                        d["content"] = content
                    if category is not None:
                        d["category"] = category
                    if source is not None:
                        d["source"] = source
                    d["updated_at"] = datetime.now(timezone.utc).isoformat()
                    self._flush()
                    return dict(d)
        return None

    def delete_doc(self, doc_id: str) -> bool:
        """删除文档"""
        with self._lock:
            for i, d in enumerate(self._docs):
                if d["doc_id"] == doc_id:
                    self._docs.pop(i)
                    self._flush()
                    return True
        return False

    def get_all_for_retriever(self) -> list[dict]:
        """获取所有文档（用于构建检索器）"""
        with self._lock:
            return [dict(d) for d in self._docs]


# 全局单例
_store: Optional[KnowledgeStore] = None


def get_knowledge_store(db_path: Optional[str] = None) -> KnowledgeStore:
    global _store
    if _store is None:
        _store = KnowledgeStore(db_path or "data/knowledge.json")
    return _store


def reset_knowledge_store():
    """重置全局单例（测试用）"""
    global _store
    _store = None
