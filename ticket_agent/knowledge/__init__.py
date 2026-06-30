"""
知识库加载器

从 KnowledgeStore 读取文档构建检索器，支持本地 KeywordRetriever
和远程 Qdrant 两种模式。文档增删改后检索器自动重建。

集成 Embedding 缓存和 Cross-encoder 精排（P0/P1 优化）。
"""
import logging
from typing import Optional

from rag.retriever import KeywordRetriever, RetrieverRoute, MultiRouteRetriever, Retriever
from rag.embedding_cache import get_embedding_cache
from rag.reranker import CrossEncoderReranker
from ticket_agent.knowledge.store import get_knowledge_store

logger = logging.getLogger(__name__)

# 全局 Qdrant 检索器缓存（按分类）
_qdrant_retrievers: dict = {}

EMBEDDING_CACHE_ENABLED = True


def _docs_to_retriever_format(docs: list[dict]) -> list[dict]:
    """将 store 中的文档格式转为 retriever 需要的格式"""
    result = []
    for doc in docs:
        result.append({
            "content": doc["content"],
            "metadata": {
                "doc_id": doc["doc_id"],
                "category": doc["category"],
                "source": doc.get("source", "知识库"),
            },
        })
    return result


def _build_qdrant_retriever(
    category: str,
    embedding,
    host: str = "localhost",
    port: int = 6333,
    top_k: int = 10,
) -> Optional[Retriever]:
    """构建 Qdrant 向量检索器（带缓存）"""
    import os

    host = os.getenv("QDRANT_HOST") or host
    port = int(os.getenv("QDRANT_PORT") or str(port))

    try:
        from rag.vector_store import QdrantVectorStore

        store = QdrantVectorStore(
            collection_name=f"ticket_knowledge_{category}",
            embedding=embedding,
            host=host,
            port=port,
            embedding_dim=1536,
            score_threshold=0.3,
        )

        # 预热：确保 collection 存在
        from qdrant_client import QdrantClient
        client = QdrantClient(url=f"http://{host}:{port}", timeout=10)
        store._ensure_collection(client)

        return Retriever(vector_store=store, top_k=top_k)
    except Exception as e:
        logger.warning(f"Qdrant 检索器构建失败（将使用纯关键词检索）: {e}")
        return None


def build_category_retriever(
    category: str,
    use_qdrant: bool = False,
    qdrant_retriever: Optional[Retriever] = None,
    top_k: int = 5,
    use_reranker: bool = False,
    reranker: Optional[CrossEncoderReranker] = None,
) -> MultiRouteRetriever:
    """
    为指定分类构建多路召回检索器

    路线1：KeywordRetriever（关键词精确匹配，开箱即用）
    路线2：Qdrant 向量检索（语义匹配，需要 Qdrant 服务）

    支持可选的 Cross-encoder 精排（通过 MultiRouteRetriever 的 post_processor 注入）
    """
    store = get_knowledge_store()
    raw_docs = store.list_docs(category)
    docs = _docs_to_retriever_format(raw_docs)

    if not docs:
        logger.warning(f"分类 [{category}] 没有知识库数据")

    routes = []
    keyword_retriever = KeywordRetriever(documents=docs, top_k=top_k * 2 if use_reranker else top_k)
    routes.append(RetrieverRoute("keyword", keyword_retriever, weight=1.0))

    if use_qdrant and qdrant_retriever:
        routes.append(RetrieverRoute("vector", qdrant_retriever, weight=1.0))

    if not routes:
        raise ValueError(f"分类 [{category}] 没有任何可用的检索路线")

    retriever = MultiRouteRetriever(routes=routes, top_k=top_k * 2 if use_reranker else top_k)

    # 如果开启了精排，在检索后自动执行 Cross-encoder
    if use_reranker and reranker:
        original_retrieve = retriever.retrieve

        async def retrieve_with_rerank(query, **kwargs):
            docs = await original_retrieve(query, **kwargs)
            if docs:
                try:
                    docs = await reranker.rerank(query, docs, top_k=top_k)
                    # 记录精排后的分数
                    for d in docs:
                        if "cross_encoder_score" in d:
                            d["score"] = d["cross_encoder_score"]
                except Exception as e:
                    logger.warning(f"Cross-encoder 精排失败（使用原始结果）: {e}")
                    docs = docs[:top_k]
            return docs

        retriever.retrieve = retrieve_with_rerank

    return retriever


def build_global_retriever(top_k: int = 5) -> MultiRouteRetriever:
    """
    构建全局检索器（不按分类过滤），用于跨分类搜索
    """
    store = get_knowledge_store()
    all_raw = store.list_docs()
    docs = _docs_to_retriever_format(all_raw)

    keyword_retriever = KeywordRetriever(documents=docs, top_k=top_k * 2)
    return MultiRouteRetriever(
        routes=[RetrieverRoute("keyword", keyword_retriever, weight=1.0)],
        top_k=top_k,
    )


def get_category_docs(category: str) -> list:
    """获取指定分类的所有知识库文档"""
    return get_knowledge_store().list_docs(category)
