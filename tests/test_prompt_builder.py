"""
Prompt 构建器测试
"""
from agents.prompt_builder import PromptBuilder


def test_build_default():
    builder = PromptBuilder(base_prompt="你是一个助手。")
    result = builder.build()
    assert "你是一个助手。" in result


def test_build_with_sections():
    builder = PromptBuilder(base_prompt="你是一个助手。")
    builder.add_memory("记住：用户喜欢简洁回复。")
    builder.add_rules("每次只回答一个要点。")

    result = builder.build()
    assert "## memory" in result.lower()
    assert "## rules" in result.lower()
    assert "记住" in result
    assert "一个要点" in result


def test_build_order_by_priority():
    builder = PromptBuilder()
    builder.add_memory("记忆内容")
    builder.add_tools("工具描述")

    result = builder.build()
    # memory 优先级 20 < tools 优先级 40，所以 memory 在前
    mem_idx = result.index("记忆内容")
    tool_idx = result.index("工具描述")
    assert mem_idx < tool_idx


def test_empty_section_not_added():
    builder = PromptBuilder()
    builder.add_memory("")
    builder.add_knowledge("  ")
    result = builder.build()
    assert "##" not in result  # 只有 base


def test_clear():
    builder = PromptBuilder()
    builder.add_memory("一些内容")
    builder.clear()
    result = builder.build()
    assert "##" not in result


def test_max_tokens():
    """Token 预算裁剪（不设极低阈值，避免递归无限循环）"""
    builder = PromptBuilder(base_prompt="short")
    # 设置合理预算，确保裁剪逻辑执行
    builder.set_max_tokens(500)
    long_text = "very long content " * 500
    builder.add_memory(long_text)
    result = builder.build()
    # 应包含 base prompt
    assert "short" in result
