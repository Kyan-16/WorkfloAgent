"""
AgentBase 单元测试
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from agents.base import AgentBase
from llm.base import LLMResponse, ChatMessage
from memory.base import MemoryMessage


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.model = "test-model"
    llm.generate = AsyncMock(return_value=LLMResponse(content="测试回复", model="test-model", finish_reason="stop"))
    return llm


@pytest.fixture
def mock_memory():
    """Memory 有 sync 和 async 方法，仅 async 方法用 AsyncMock"""
    memory = MagicMock()
    memory.get_history = AsyncMock(return_value=[])
    memory.add = AsyncMock(return_value=True)
    return memory


@pytest.mark.asyncio
async def test_chat_basic(mock_llm, mock_memory):
    """测试基本对话流程"""
    agent = AgentBase(llm=mock_llm, memory=mock_memory, system_prompt="你是一个助手")
    response = await agent.chat("你好", session_id="test1")

    assert response.content == "测试回复"
    assert response.session_id == "test1"
    assert response.model == "test-model"
    mock_llm.generate.assert_called_once()
    assert mock_memory.add.await_count >= 2


@pytest.mark.asyncio
async def test_chat_empty_input(mock_llm, mock_memory):
    """测试空输入校验"""
    agent = AgentBase(llm=mock_llm, memory=mock_memory)
    with pytest.raises(ValueError, match="user_input 不能为空"):
        await agent.chat("", session_id="s1")


@pytest.mark.asyncio
async def test_chat_whitespace_input(mock_llm, mock_memory):
    """测试空白输入校验"""
    agent = AgentBase(llm=mock_llm, memory=mock_memory)
    with pytest.raises(ValueError, match="user_input 不能为空"):
        await agent.chat("   ", session_id="s1")


@pytest.mark.asyncio
async def test_chat_long_input(mock_llm, mock_memory):
    """测试超长输入校验"""
    agent = AgentBase(llm=mock_llm, memory=mock_memory)
    with pytest.raises(ValueError, match="user_input 过长"):
        await agent.chat("x" * 32001, session_id="s1")


@pytest.mark.asyncio
async def test_chat_empty_session_id(mock_llm, mock_memory):
    """测试空 session_id 校验"""
    agent = AgentBase(llm=mock_llm, memory=mock_memory)
    with pytest.raises(ValueError, match="session_id 不能为空"):
        await agent.chat("你好", session_id="")


@pytest.mark.asyncio
async def test_chat_with_rag(mock_llm):
    """测试 RAG 检索集成"""
    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock(return_value=[
        {"content": "这是参考资料内容", "score": 0.95, "metadata": {"source": "kb"}}
    ])

    agent = AgentBase(llm=mock_llm, retriever=mock_retriever)
    response = await agent.chat("测试RAG", session_id="rag_test")

    assert response.content == "测试回复"
    assert len(response.sources) == 1
    assert response.sources[0]["score"] == 0.95
    mock_retriever.retrieve.assert_awaited_once_with("测试RAG")


@pytest.mark.asyncio
async def test_chat_no_rag(mock_llm):
    """测试关闭 RAG"""
    mock_retriever = MagicMock()
    mock_retriever.retrieve = AsyncMock()

    agent = AgentBase(llm=mock_llm, retriever=mock_retriever)
    await agent.chat("测试", session_id="no_rag", use_rag=False)

    mock_retriever.retrieve.assert_not_awaited()


@pytest.mark.asyncio
async def test_chat_with_history(mock_llm):
    """测试对话历史加载"""
    mock_memory = MagicMock()
    mock_memory.get_history = AsyncMock(return_value=[
        MemoryMessage(role="user", content="之前的问题"),
        MemoryMessage(role="assistant", content="之前的回复"),
    ])
    mock_memory.add = AsyncMock(return_value=True)

    agent = AgentBase(llm=mock_llm, memory=mock_memory)
    response = await agent.chat("新问题", session_id="history_test")

    assert response.content == "测试回复"
    call_args = mock_llm.generate.call_args
    messages = call_args.kwargs["messages"]
    roles = [m.role for m in messages]
    assert "user" in roles
    assert "assistant" in roles


@pytest.mark.asyncio
async def test_chat_llm_error(mock_memory):
    """测试 LLM 失败时抛出异常"""
    mock_llm = MagicMock()
    mock_llm.model = "test-model"
    mock_llm.generate = AsyncMock(side_effect=RuntimeError("LLM 调用失败"))

    agent = AgentBase(llm=mock_llm, memory=mock_memory)
    with pytest.raises(RuntimeError, match="LLM 调用失败"):
        await agent.chat("你好", session_id="s1")
