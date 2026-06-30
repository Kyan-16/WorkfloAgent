"""
模型 → Provider 自动映射

简化用户配置：只需设置模型名称，系统自动推导出 Provider、API Key 环境变量。
类似 CowAgent 的 _MODEL_PREFIX_MAP 机制。

使用方式：
    # 用户只需设置 LLM_MODEL=deepseek-chat
    info = resolve_model("deepseek-chat")
    # → {"provider": "openai", "api_key_var": "DEEPSEEK_API_KEY", ...}

    # 高级用户可以为不同 Agent 角色设置不同模型
    LLM_MODEL=qwen-plus              # 全局默认
    CLASSIFIER_LLM_MODEL=gpt-4o-mini  # 分类用便宜小模型
    EXECUTOR_LLM_MODEL=deepseek-chat  # 执行用性价比模型
"""

from dataclasses import dataclass, field
from typing import Optional

from llm.base import LLMBase


# ── 模型前缀 → Provider 映射表（顺序敏感：前缀长的放前面）──
# 格式: (前缀, provider名, api_key_env_var, base_url_env_var)
MODEL_PREFIX_MAP = [
    # DeepSeek
    ("deepseek-reasoner", "openai", "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL"),
    ("deepseek-chat",     "openai", "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL"),
    ("deepseek-v3",       "openai", "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL"),
    # Qwen (DashScope)
    ("qwen3-max",         "dashscope", "DASHSCOPE_API_KEY", ""),
    ("qwen3-plus",        "dashscope", "DASHSCOPE_API_KEY", ""),
    ("qwen-max",          "dashscope", "DASHSCOPE_API_KEY", ""),
    ("qwen-plus",         "dashscope", "DASHSCOPE_API_KEY", ""),
    ("qwen-turbo",        "dashscope", "DASHSCOPE_API_KEY", ""),
    ("qwen2",             "dashscope", "DASHSCOPE_API_KEY", ""),
    ("text-embedding-v2", "dashscope", "DASHSCOPE_API_KEY", ""),
    ("text-embedding-v3", "dashscope", "DASHSCOPE_API_KEY", ""),
    # GPT / OpenAI
    ("gpt-4o",            "openai", "OPENAI_API_KEY", "OPENAI_BASE_URL"),
    ("gpt-4-turbo",       "openai", "OPENAI_API_KEY", "OPENAI_BASE_URL"),
    ("gpt-4",             "openai", "OPENAI_API_KEY", "OPENAI_BASE_URL"),
    ("gpt-3.5-turbo",     "openai", "OPENAI_API_KEY", "OPENAI_BASE_URL"),
    ("o1",                "openai", "OPENAI_API_KEY", "OPENAI_BASE_URL"),
    ("o3-mini",           "openai", "OPENAI_API_KEY", "OPENAI_BASE_URL"),
    # Moonshot / Kimi
    ("moonshot",          "openai", "MOONSHOT_API_KEY", "MOONSHOT_BASE_URL"),
    ("kimi",              "openai", "MOONSHOT_API_KEY", "MOONSHOT_BASE_URL"),
    # 智谱 GLM
    ("glm-4",             "openai", "ZHIPU_API_KEY", "ZHIPU_BASE_URL"),
    ("glm-3",             "openai", "ZHIPU_API_KEY", "ZHIPU_BASE_URL"),
    # 零一万物
    ("yi-",               "openai", "YI_API_KEY", "YI_BASE_URL"),
    # Doubao (火山引擎)
    ("doubao",            "openai", "DOUBAO_API_KEY", "DOUBAO_BASE_URL"),
    # Claude (OpenAI 兼容)
    ("claude-3-5",        "openai", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"),
    ("claude-3",          "openai", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"),
    ("claude-opus",       "openai", "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"),
    # Gemini
    ("gemini",            "openai", "GEMINI_API_KEY", "GEMINI_BASE_URL"),
    # Minimax
    ("minimax",           "openai", "MINIMAX_API_KEY", "MINIMAX_BASE_URL"),
]

# 默认 API Key 环境变量（当模型无对应 provider 时的回退）
DEFAULT_API_KEY_ENV = "LLM_API_KEY"
DEFAULT_BASE_URL_ENV = "LLM_BASE_URL"


@dataclass
class ModelInfo:
    """模型解析结果"""
    model: str
    provider: str = ""
    api_key: str = ""
    base_url: Optional[str] = None
    api_key_env_var: str = ""
    base_url_env_var: str = ""


def resolve_model(model_name: str) -> ModelInfo:
    """
    根据模型名称自动解析 Provider 和 API Key 配置。

    过程：
    1. 在 MODEL_PREFIX_MAP 中查找匹配的前缀
    2. 读取对应的环境变量获取 API Key 和 Base URL
    3. 未匹配时回退到全局 LLM_API_KEY / LLM_BASE_URL

    Args:
        model_name: 模型名称（如 "deepseek-chat", "gpt-4o", "qwen-plus"）

    Returns:
        ModelInfo: 包含 provider, api_key, base_url 等信息

    Raises:
        ValueError: 未知模型且无法回退时
    """
    import os
    model_lower = model_name.lower().strip()

    info = ModelInfo(model=model_name)

    # 1. 在映射表中查找
    for prefix, provider, key_var, base_var in MODEL_PREFIX_MAP:
        if model_lower.startswith(prefix):
            info.provider = provider
            info.api_key_env_var = key_var
            info.base_url_env_var = base_var
            break

    # 2. 读取环境变量
    if info.api_key_env_var:
        info.api_key = os.getenv(info.api_key_env_var, "")
    if not info.api_key:
        info.api_key = os.getenv(DEFAULT_API_KEY_ENV, "")

    if info.base_url_env_var:
        info.base_url = os.getenv(info.base_url_env_var) or os.getenv(DEFAULT_BASE_URL_ENV)

    # 3. 未匹配 → 使用默认环境变量
    if not info.provider:
        info.provider = "openai"
        info.api_key = os.getenv(DEFAULT_API_KEY_ENV, "")
        info.base_url = os.getenv(DEFAULT_BASE_URL_ENV)

    return info


def resolve_model_from_env(env_var: str = "LLM_MODEL") -> ModelInfo:
    """
    从环境变量读取模型名称并解析。

    Args:
        env_var: 环境变量名（如 "LLM_MODEL", "CLASSIFIER_LLM_MODEL"）

    Returns:
        ModelInfo
    """
    import os
    model_name = os.getenv(env_var, "")
    if not model_name:
        # 回退到 LLM_MODEL
        model_name = os.getenv("LLM_MODEL", "qwen-plus")
    return resolve_model(model_name)


def create_llm_from_model(model_name: str, **overrides) -> LLMBase:
    """
    从模型名称创建 LLM 实例（最简调用方式）。

    用户只需指定模型名，自动推导 Provider 和 API Key。

    使用示例：
        llm = create_llm_from_model("deepseek-chat")
        llm = create_llm_from_model("gpt-4o", temperature=0.3)

    Args:
        model_name: 模型名称
        **overrides: 覆盖参数（temperature, max_tokens 等）

    Returns:
        LLMBase 实例
    """
    from llm.factory import create_llm

    info = resolve_model(model_name)
    config = {
        "provider": info.provider,
        "model": model_name,
        "api_key": info.api_key,
    }
    if info.base_url:
        config["base_url"] = info.base_url
    config.update(overrides)
    return create_llm(config)
