"""
Token 估计器测试
"""
from llm.token_estimator import (
    estimate_text_tokens, estimate_message_tokens,
    get_model_context_window, get_context_usage_ratio, should_trim,
)


def test_estimate_text_empty():
    assert estimate_text_tokens(None) == 0
    assert estimate_text_tokens("") == 0


def test_estimate_text_cjk_vs_ascii():
    cjk = estimate_text_tokens("你好世界")
    ascii = estimate_text_tokens("hello")
    assert cjk > ascii, "CJK should cost more than ASCII"


def test_estimate_text_mixed():
    mixed = estimate_text_tokens("你好 world")
    ascii = estimate_text_tokens("hello")
    assert mixed > ascii


def test_estimate_messages():
    messages = [
        {"role": "system", "content": "你是一个助手"},
        {"role": "user", "content": "你好"},
    ]
    total = estimate_message_tokens(messages)
    assert total > 0


def test_estimate_messages_empty():
    assert estimate_message_tokens([]) == 0
    assert estimate_message_tokens(None) == 0


def test_model_context_window_known():
    assert get_model_context_window("gpt-4o") == 128000
    assert get_model_context_window("deepseek-chat") == 65536
    assert get_model_context_window("qwen-plus") == 131072


def test_model_context_window_default():
    assert get_model_context_window("unknown-model") == 8192
    assert get_model_context_window(None) == 8192


def test_context_usage_ratio():
    messages = [{"role": "user", "content": "hi"}]
    ratio = get_context_usage_ratio(messages, "gpt-4o")
    assert 0 < ratio < 0.01


def test_should_trim():
    messages = [{"role": "user", "content": "hi"}]
    assert not should_trim(messages, "gpt-4o")
    # 极低阈值触发裁剪
    assert should_trim(messages, "gpt-4o", threshold=0.00001)
