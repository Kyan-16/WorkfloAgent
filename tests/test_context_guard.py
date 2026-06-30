"""
上下文管理 + 幻觉防护 测试
"""
from agents.context_guard import (
    trim_context,
    HallucinationGuard,
    enhance_system_prompt,
)
from llm.base import ChatMessage


class TestTrimContext:

    def test_no_trim_when_below_threshold(self):
        messages = [ChatMessage(role="system", content="你是一个助手")]
        result = trim_context(messages, model_name="gpt-4o")
        assert len(result) == 1  # 不应裁剪

    def test_trim_preserves_system(self):
        messages = [
            ChatMessage(role="system", content="system"),
            ChatMessage(role="user", content="你好"),
        ]
        result = trim_context(messages, model_name="gpt-4o")
        assert any(m.role == "system" for m in result)
        assert len(result) >= 1

    def test_trim_preserves_recent(self):
        messages = (
            [ChatMessage(role="system", content="sys")]
            + [ChatMessage(role="user", content=f"msg{i}") for i in range(100)]
        )
        result = trim_context(messages, model_name="gpt-4", threshold=0.01)
        assert len(result) < len(messages)
        # 最近的几条应该保留
        assert result[-1].content == "msg99"


class TestHallucinationGuard:

    def test_safe_response(self):
        result = HallucinationGuard.check_response(
            "您可以联系 IT 部门处理。",
            rag_context="联系 IT 部门处理电脑蓝屏问题",
        )
        assert result["safe"]

    def test_honest_declaration(self):
        result = HallucinationGuard.check_response(
            "我不确定这个问题的答案，建议您联系 IT 部门。"
        )
        assert result["safe"]

    def test_vague_claim_warning(self):
        result = HallucinationGuard.check_response(
            "据我所知，这种情况通常需要重启服务器。"
        )
        assert result["risk"] == "medium"
        assert len(result["warnings"]) > 0

    def test_check_with_numbers_no_rag(self):
        """包含具体数字但没有 RAG 支撑时应有警告"""
        result = HallucinationGuard.check_response(
            "90% 的电脑蓝屏都是内存问题导致的。"
        )
        assert result["risk"] == "medium"

    def test_safety_prompt_contains_keywords(self):
        prompt = HallucinationGuard.safety_prompt_suffix()
        assert "我不知道" in prompt
        assert "编造" in prompt
        assert "参考资料" in prompt

    def test_enhance_system_prompt(self):
        original = "你是一个助手。"
        enhanced = enhance_system_prompt(original)
        assert enhanced.startswith("你是一个助手。")
        assert "回答原则" in enhanced

    def test_enhance_does_not_duplicate(self):
        once = enhance_system_prompt("你是一个助手。")
        twice = enhance_system_prompt(once)
        assert twice == once  # 不应重复追加
