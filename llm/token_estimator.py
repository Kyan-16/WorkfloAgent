"""
Token 估算工具

按模型上下文窗口 + 字符类型（CJK/ASCII）估算 token 消耗。
用于上下文预算管理，在超出窗口 80% 时触发裁剪。

支持模型上下文窗口映射：
- GPT-4o: 128K
- DeepSeek Chat: 64K
- Qwen-Plus/Max: 32K-128K
- Claude 3/3.5: 200K

使用示例：
    token_count = estimate_text_tokens("你好世界 Hello")
    total = estimate_message_tokens(messages)
    window = get_model_context_window("gpt-4o")
    ratio = total / window  # 使用率
"""

from typing import Optional

# 模型 → 上下文窗口大小映射
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # OpenAI
    "gpt-4o": 128000,
    "gpt-4-turbo": 128000,
    "gpt-4": 8192,
    "gpt-3.5-turbo": 16384,
    "o1": 200000,
    "o3-mini": 200000,
    # DeepSeek
    "deepseek-chat": 65536,
    "deepseek-reasoner": 65536,
    "deepseek-v3": 65536,
    # DashScope / Qwen
    "qwen-max": 32768,
    "qwen-plus": 131072,
    "qwen-turbo": 131072,
    "qwen3-max": 131072,
    "qwen3-plus": 131072,
    "qwen2": 131072,
    # Claude
    "claude-3-5-sonnet": 200000,
    "claude-3-sonnet": 200000,
    "claude-3-haiku": 200000,
    "claude-3-opus": 200000,
    # Moonshot
    "moonshot": 131072,
    # GLM / 智谱
    "glm-4": 131072,
    "glm-3": 131072,
}

# 默认窗口（当模型未匹配时）
_DEFAULT_CONTEXT_WINDOW = 8192


def _is_cjk(char: str) -> bool:
    """判断是否为 CJK（中日韩）字符"""
    cp = ord(char)
    return (
        (0x4E00 <= cp <= 0x9FFF) or    # CJK Unified Ideographs
        (0x3400 <= cp <= 0x4DBF) or    # CJK Extension A
        (0x2E80 <= cp <= 0x2EFF) or    # CJK Radicals
        (0x3000 <= cp <= 0x303F) or    # CJK Symbols
        (0xFF00 <= cp <= 0xFFEF)       # Fullwidth Forms
    )


def estimate_text_tokens(text: Optional[str]) -> int:
    """
    估算文本的 token 数（CJK 感知）。

    规则：
    - CJK 字符: 约 1.5 tokens/字符
    - ASCII 字符: 约 0.25 tokens/字符
    - 固定 +1 开销

    Args:
        text: 要估算的文本

    Returns:
        估算的 token 数
    """
    if not text:
        return 0

    cjk_count = sum(1 for c in text if _is_cjk(c))
    ascii_count = len(text) - cjk_count

    return int(cjk_count * 1.5 + ascii_count * 0.25) + 1


def estimate_message_tokens(messages: list[dict]) -> int:
    """
    估算消息列表的总 token 数。

    包含：
    - 每条消息的 content/role 开销
    - tool_calls 开销
    - 消息间分隔 overhead

    Args:
        messages: ChatMessage 的 dict 列表

    Returns:
        估算的总 token 数
    """
    if not messages:
        return 0

    total = 0
    for msg in messages:
        # 消息内容
        content = msg.get("content", "") or ""
        if isinstance(content, str):
            total += estimate_text_tokens(content)
        elif isinstance(content, list):
            # 多模态 content（包含 image_url 等）
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += estimate_text_tokens(part.get("text", ""))

        # tool_calls 固定开销
        tool_calls = msg.get("tool_calls")
        if tool_calls:
            total += 50 * len(tool_calls)

        # 每条消息的 role 等 overhead
        total += 4

    return total


def get_model_context_window(model_name: Optional[str]) -> int:
    """
    获取模型的上下文窗口大小。

    通过模型名称模糊匹配（子串匹配），
    未匹配时返回默认值 8192。

    Args:
        model_name: 模型名称（如 "gpt-4o", "deepseek-chat"）

    Returns:
        上下文窗口大小（tokens）
    """
    if not model_name:
        return _DEFAULT_CONTEXT_WINDOW

    model_lower = model_name.lower()

    for key, window in MODEL_CONTEXT_WINDOWS.items():
        if key in model_lower:
            return window

    return _DEFAULT_CONTEXT_WINDOW


def get_context_usage_ratio(messages: list[dict], model_name: Optional[str] = None) -> float:
    """
    计算当前消息列表占上下文窗口的比例。

    Args:
        messages: 消息列表
        model_name: 模型名称（用于获取窗口大小）

    Returns:
        使用率（0.0 ~ 1.0），超过 1.0 表示超出窗口
    """
    token_count = estimate_message_tokens(messages)
    window = get_model_context_window(model_name)
    return token_count / window if window > 0 else 0.0


def should_trim(messages: list[dict], model_name: Optional[str] = None,
                threshold: float = 0.8) -> bool:
    """
    判断是否需要裁剪上下文。

    Args:
        messages: 消息列表
        model_name: 模型名称
        threshold: 触发裁剪的阈值（默认 80%）

    Returns:
        是否应裁剪
    """
    return get_context_usage_ratio(messages, model_name) >= threshold
