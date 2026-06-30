"""
TaskAgent ReAct 循环单元测试
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.task_agent import TaskAgent
from llm.base import LLMResponse, ChatMessage
from tools.base import ToolResult
from tools.registry import ToolRegistry


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.model = "test-model"
    # generate() 是 async 方法，用 AsyncMock 包装
    llm.generate = AsyncMock()
    return llm


@pytest.fixture
def mock_tool():
    """创建模拟工具"""
    tool = MagicMock()
    tool.name = "test_tool"
    tool.description = "测试工具"
    tool.parameters = {}
    tool.execute = AsyncMock(return_value=ToolResult(success=True, output="工具执行成功"))
    return tool


@pytest.fixture
def mock_registry(mock_tool):
    """创建模拟工具注册表（同步方法）"""
    registry = MagicMock(spec=ToolRegistry)
    registry.get_function_schemas.return_value = [
        {"name": "test_tool", "description": "测试工具", "parameters": {}}
    ]
    registry.call_from_llm_response = AsyncMock(return_value=ToolResult(success=True, output="工具执行成功"))
    registry.tools = {"test_tool": mock_tool}
    return registry


@pytest.mark.asyncio
async def test_react_direct_answer(mock_llm, mock_registry):
    """测试 LLM 直接回答（无工具调用）"""
    mock_llm.generate.return_value = LLMResponse(content="直接回复", model="test-model", finish_reason="stop")
    agent = TaskAgent(llm=mock_llm, tool_registry=mock_registry, max_tool_rounds=5)
    response = await agent.chat("你好", session_id="test1")

    assert response.content == "直接回复"
    assert len(response.tool_calls) == 0
    mock_llm.generate.assert_called_once()


@pytest.mark.asyncio
async def test_react_one_tool_call(mock_llm, mock_registry):
    """测试单次工具调用后回答"""
    mock_llm.generate.side_effect = [
        LLMResponse(
            content="",
            model="test-model",
            finish_reason="tool_calls",
            tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "test_tool", "arguments": "{}"}}],
        ),
        LLMResponse(content="工具调用后的回答", model="test-model", finish_reason="stop"),
    ]
    agent = TaskAgent(llm=mock_llm, tool_registry=mock_registry, max_tool_rounds=5)
    response = await agent.chat("帮我查一下", session_id="tool_test")

    assert response.content == "工具调用后的回答"
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0]["tool"] == "test_tool"
    assert response.tool_calls[0]["success"] is True
    mock_llm.generate.assert_called()


@pytest.mark.asyncio
async def test_react_max_rounds_fallback(mock_llm, mock_registry):
    """测试达到最大工具调用轮次时自动兜底"""
    mock_llm.generate.return_value = LLMResponse(
        content="",
        model="test-model",
        finish_reason="tool_calls",
        tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "test_tool", "arguments": "{}"}}],
    )
    agent = TaskAgent(llm=mock_llm, tool_registry=mock_registry, max_tool_rounds=3)
    response = await agent.chat("重复工具调用", session_id="max_test")

    assert "工具调用" in response.content
    assert "3 轮" in response.content


@pytest.mark.asyncio
async def test_react_empty_llm_response(mock_llm, mock_registry):
    """测试 LLM 返回 None 时抛出 RuntimeError"""
    mock_llm.generate.return_value = None
    agent = TaskAgent(llm=mock_llm, tool_registry=mock_registry)
    with pytest.raises(RuntimeError, match="LLM 未返回响应"):
        await agent.chat("测试", session_id="s1")


@pytest.mark.asyncio
async def test_react_security_block(mock_llm):
    """测试安全守卫拦截工具调用"""
    from ticket_agent.security.tool_guard import ToolGuard

    with patch.object(ToolGuard, "check", return_value=(False, "频率限制")):
        mock_llm.generate.side_effect = [
            LLMResponse(
                content="",
                model="test-model",
                finish_reason="tool_calls",
                tool_calls=[{"id": "c1", "type": "function", "function": {"name": "blocked_tool", "arguments": "{}"}}],
            ),
            LLMResponse(content="已处理", model="test-model", finish_reason="stop"),
        ]

        mock_registry = MagicMock(spec=ToolRegistry)
        mock_registry.get_function_schemas.return_value = [{"name": "blocked_tool"}]

        agent = TaskAgent(llm=mock_llm, tool_registry=mock_registry, max_tool_rounds=3)
        response = await agent.chat("测试拦截", session_id="security_test")
        assert response.content == "已处理"
