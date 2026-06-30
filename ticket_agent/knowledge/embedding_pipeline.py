"""
知识库自动 Embedding Pipeline

当知识库文档被添加/更新/删除时，自动同步到 Qdrant 向量数据库。
使用异步后台任务，不阻塞 API 响应。

流程：
知识库变更 → 事件入队 → 异步 Worker → Embedding → Qdrant Upsert

使用示例：
    pipeline = EmbeddingPipeline()
    await pipeline.on_doc_added(doc_id="kb_001", content="...", category="IT")
"""
import asyncio
import json
import logging
import os
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class EmbeddingPipeline:
    """
    自动 Embedding Pipeline

    监听知识库变更事件，自动同步到 Qdrant。

    设计原理：
    - 用内存队列收集变更事件
    - 批量去重后统一处理（避免频繁 Embedding API 调用）
    - 失败自动重试，不阻塞主流程
    """

    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._batch_lock = threading.Lock()
        self._pending: dict[str, dict] = {}
        self._running = False

    async def start(self):
        """启动后台 Worker"""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("Embedding Pipeline Worker 已启动")

    async def stop(self):
        """停止后台 Worker"""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("Embedding Pipeline Worker 已停止")

    async def on_doc_added(self, doc_id: str, content: str, category: str):
        """文档新增事件"""
        await self._enqueue("add", doc_id, content, category)

    async def on_doc_updated(self, doc_id: str, content: str, category: str):
        """文档更新事件"""
        await self._enqueue("update", doc_id, content, category)

    async def on_doc_deleted(self, doc_id: str):
        """文档删除事件"""
        await self._enqueue("delete", doc_id, "", "")

    async def _enqueue(self, action: str, doc_id: str, content: str, category: str):
        """入队（去重：同 doc_id 的旧事件被覆盖）"""
        with self._batch_lock:
            self._pending[doc_id] = {
                "action": action,
                "doc_id": doc_id,
                "content": content,
                "category": category,
            }

    async def _worker_loop(self):
        """后台 Worker 主循环：每 5 秒批量处理一次"""
        while self._running:
            try:
                await asyncio.sleep(5)
                await self._flush_batch()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Embedding Worker 异常: {e}")

    async def _flush_batch(self):
        """批量刷新：将待处理事件一次发送到 Qdrant"""
        # 取出当前所有待处理事件
        with self._batch_lock:
            if not self._pending:
                return
            batch = dict(self._pending)
            self._pending.clear()

        if not batch:
            return

        # 检查 Qdrant 是否可用
        qdrant_host = os.getenv("QDRANT_HOST", "localhost")
        qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))
        if not self._check_qdrant(qdrant_host, qdrant_port):
            logger.debug("Qdrant 不可用，跳过 Embedding 同步")
            return

        try:
            await self._sync_to_qdrant(batch, qdrant_host, qdrant_port)
        except Exception as e:
            logger.warning(f"Qdrant 同步失败（下次重试）: {e}")

    def _check_qdrant(self, host: str, port: int) -> bool:
        """快速检查 Qdrant 是否可达"""
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(2)
            result = s.connect_ex((host, port))
            s.close()
            return result == 0
        except Exception:
            return False

    async def _sync_to_qdrant(self, batch: dict[str, dict], host: str, port: int):
        """同步到 Qdrant"""
        try:
            from rag.embeddings import create_embedding
            from rag.vector_store import QdrantVectorStore

            api_key = os.getenv("EMBEDDING_API_KEY") or os.getenv("LLM_API_KEY", "")
            embedding = create_embedding(
                provider=os.getenv("EMBEDDING_PROVIDER", "dashscope"),
                model=os.getenv("EMBEDDING_MODEL", "text-embedding-v2"),
                api_key=api_key,
            )

            # 按分类分组，每个分类一个 collection
            by_category: dict[str, list[dict]] = {}
            for doc_id, event in batch.items():
                cat = event["category"] or "general"
                if cat not in by_category:
                    by_category[cat] = []
                by_category[cat].append(event)

            for category, events in by_category.items():
                collection_name = f"ticket_knowledge_{category}"
                store = QdrantVectorStore(
                    collection_name=collection_name,
                    embedding=embedding,
                    host=host,
                    port=port,
                    embedding_dim=1536,
                )

                # 处理删除
                deletes = [e for e in events if e["action"] == "delete"]
                if deletes:
                    try:
                        from qdrant_client import QdrantClient
                        client = QdrantClient(url=f"http://{host}:{port}", timeout=10)
                        from qdrant_client.http import models
                        delete_ids = [e["doc_id"] for e in deletes]
                        client.delete(
                            collection_name=collection_name,
                            points_selector=models.Filter(
                                must=[models.FieldCondition(
                                    key="doc_id",
                                    match=models.MatchValue(value=did),
                                ) for did in delete_ids],
                            ),
                        )
                        logger.info(f"Qdrant 删除: {collection_name} {len(delete_ids)} 条")
                    except Exception as e:
                        logger.warning(f"Qdrant 删除失败: {e}")

                # 处理新增/更新
                upserts = [e for e in events if e["action"] in ("add", "update")]
                if upserts:
                    texts = [e["content"] for e in upserts]
                    metadatas = [
                        {"doc_id": e["doc_id"], "category": e["category"]}
                        for e in upserts
                    ]
                    ids = await store.add_texts(texts, metadatas)
                    if ids:
                        logger.info(
                            f"Qdrant 同步: {collection_name} "
                            f"{len(ids)} 条 (成功/总数: {len(ids)}/{len(texts)})"
                        )

        except Exception as e:
            logger.error(f"Qdrant 同步异常: {e}")
            raise


# 全局单例
_pipeline: Optional[EmbeddingPipeline] = None


def get_embedding_pipeline() -> EmbeddingPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = EmbeddingPipeline()
    return _pipeline


def reset_embedding_pipeline():
    global _pipeline
    _pipeline = None
