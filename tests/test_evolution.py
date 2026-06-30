"""
自我进化系统测试
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ticket_agent.evolution.trigger import EvolutionTrigger
from ticket_agent.evolution.prompts import EvolutionPrompts
from ticket_agent.evolution.executor import EvolutionExecutor


class TestEvolutionTrigger:

    def test_force_trigger(self):
        t = EvolutionTrigger()
        ok, reason = t.should_evolve(force=True)
        assert ok
        assert "强制触发" in reason

    def test_trigger_by_user_keyword(self):
        t = EvolutionTrigger()
        ok, reason = t.should_evolve(user_input="请记住这个配置")
        assert ok
        assert "用户意图触发" in reason

    def test_no_trigger_empty(self):
        t = EvolutionTrigger(min_interval_minutes=9999)
        ok, reason = t.should_evolve()
        assert not ok
        assert reason == ""

    def test_trigger_by_tool_rounds(self):
        t = EvolutionTrigger(tool_round_threshold=3)
        ok, reason = t.should_evolve(tool_rounds=5)
        assert ok
        assert "工具调用轮次" in reason

    def test_reset(self):
        t = EvolutionTrigger()
        t.should_evolve(force=True)
        assert t.get_time_since_last() is not None
        t.reset()
        assert t.get_time_since_last() is None


class TestEvolutionPrompts:

    def test_build_review_messages(self):
        messages = EvolutionPrompts.build_review_messages(
            topic="测试",
            content="这是一段对话内容",
            current_memory="- 现有记忆",
        )
        assert len(messages) == 2
        assert messages[0].role == "system"
        assert messages[1].role == "user"
        assert "测试" in messages[1].content


class TestEvolutionExecutor:

    @pytest.mark.asyncio
    async def test_try_evolve_no_trigger(self):
        """测试不触发时返回 SILENT"""
        llm = MagicMock()
        # 不满足任何触发条件，不应调 LLM
        executor = EvolutionExecutor(llm=llm)
        executor.trigger = EvolutionTrigger(min_interval_minutes=9999)

        result = await executor.try_evolve(
            topic="test",
            content="test",
            current_memory="",
        )
        assert "[SILENT]" in result
        # 确认没有调用 LLM
        llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_try_evolve_force_silent(self):
        """测试强制触发但 Review Agent 返回 silent"""
        llm = AsyncMock()
        llm.generate.return_value = MagicMock()
        llm.generate.return_value.finish_reason = "stop"
        llm.generate.return_value.content = '{"action": "silent", "reason": "无新内容", "confidence": 0.9}'

        executor = EvolutionExecutor(llm=llm)
        result = await executor.try_evolve(
            topic="test", content="test", current_memory="", force=True,
        )
        assert "[SILENT]" in result
        llm.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_concurrent_limit(self):
        """测试并发上限"""
        llm = MagicMock()
        executor = EvolutionExecutor(llm=llm)

        # 手动占用所有槽位
        EvolutionExecutor._active_count = 2

        result = await executor.try_evolve(
            topic="test", content="test", current_memory="", force=True,
        )
        assert "并发上限" in result

        # 恢复
        EvolutionExecutor._active_count = 0
