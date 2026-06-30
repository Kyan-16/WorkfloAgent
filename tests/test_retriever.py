"""
检索器 单元测试
"""
import pytest
from unittest.mock import AsyncMock

from rag.retriever import Retriever, KeywordRetriever, MultiRouteRetriever, RetrieverRoute


@pytest.mark.asyncio
async def test_retriever_retrieve():
    """测试基本检索"""
    vector_store = AsyncMock()
    vector_store.similarity_search.return_value = [
        {"content": "文档1内容", "score": 0.95, "metadata": {"source": "kb"}},
        {"content": "文档2内容", "score": 0.85, "metadata": {"source": "wiki"}},
    ]

    retriever = Retriever(vector_store=vector_store, top_k=5)
    docs = await retriever.retrieve("查询内容")

    assert len(docs) == 2
    assert docs[0]["content"] == "文档1内容"
    assert docs[0]["score"] == 0.95
    vector_store.similarity_search.assert_awaited_once_with(query="查询内容", k=5, filter=None)


@pytest.mark.asyncio
async def test_retriever_score_threshold():
    """测试分数阈值过滤"""
    vector_store = AsyncMock()
    vector_store.similarity_search.return_value = [
        {"content": "文档1", "score": 0.5, "metadata": {}},
        {"content": "文档2", "score": 0.3, "metadata": {}},
    ]

    retriever = Retriever(vector_store=vector_store, top_k=5, score_threshold=0.4)
    docs = await retriever.retrieve("查询")

    assert len(docs) == 1
    assert docs[0]["content"] == "文档1"


def test_format_context():
    """测试上下文格式化"""
    docs = [
        {"content": "文档A内容", "score": 0.95, "metadata": {"source": "kb"}},
        {"content": "文档B内容", "score": 0.80, "metadata": {"source": "wiki"}},
    ]
    context = Retriever.format_context(docs)
    assert "[参考1]" in context
    assert "[参考2]" in context
    assert "文档A内容" in context
    assert "文档B内容" in context
    assert "相关度: 0.95" in context


def test_format_context_empty():
    """测试空文档格式化"""
    context = Retriever.format_context([])
    assert context == ""


@pytest.mark.asyncio
async def test_keyword_retriever_basic():
    """测试关键词检索"""
    docs = [
        {"content": "电脑蓝屏了怎么办", "metadata": {"id": "1"}},
        {"content": "打印机无法连接", "metadata": {"id": "2"}},
        {"content": "申请新的办公用品", "metadata": {"id": "3"}},
    ]
    retriever = KeywordRetriever(documents=docs, top_k=5)
    results = await retriever.retrieve("电脑蓝屏")
    assert len(results) > 0
    assert results[0]["retrieval_route"] == "keyword"


@pytest.mark.asyncio
async def test_keyword_retriever_empty_query():
    """测试空查询"""
    retriever = KeywordRetriever(documents=[], top_k=5)
    results = await retriever.retrieve("")
    assert results == []


@pytest.mark.asyncio
async def test_keyword_retriever_filter():
    """测试关键词检索的过滤条件"""
    docs = [
        {"content": "电脑蓝屏", "metadata": {"category": "it", "id": "1"}},
        {"content": "申请假期", "metadata": {"category": "hr", "id": "2"}},
    ]
    retriever = KeywordRetriever(documents=docs, top_k=5)
    results = await retriever.retrieve("电脑", filter={"category": "it"})
    assert len(results) == 1
    assert results[0]["content"] == "电脑蓝屏"


@pytest.mark.asyncio
async def test_multi_route_retriever():
    """测试多路召回融合"""
    vector_store = AsyncMock()
    vector_store.similarity_search.return_value = [
        {"content": "向量结果", "score": 0.9, "metadata": {"source": "vector"}},
    ]

    keyword_docs = [
        {"content": "关键词结果", "metadata": {"id": "kw1"}},
    ]

    vector_retriever = Retriever(vector_store=vector_store, top_k=5)
    keyword_retriever = KeywordRetriever(documents=keyword_docs, top_k=5)

    multi = MultiRouteRetriever(
        routes=[
            RetrieverRoute(name="vector", retriever=vector_retriever, weight=1.0),
            RetrieverRoute(name="keyword", retriever=keyword_retriever, weight=0.8),
        ],
        top_k=5,
    )

    results = await multi.retrieve("测试查询")
    assert len(results) > 0


def test_multi_route_empty_routes():
    """测试空路线抛出异常"""
    with pytest.raises(ValueError, match="至少需要一条检索路线"):
        MultiRouteRetriever(routes=[])
