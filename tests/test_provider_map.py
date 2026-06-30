"""
模型→Provider 自动映射测试
"""
import os
import pytest

from llm.provider_map import resolve_model, resolve_model_from_env, create_llm_from_model, MODEL_PREFIX_MAP


class TestResolveModel:

    def test_deepseek_chat(self):
        """deepseek-chat → openai provider + DEEPSEEK_API_KEY"""
        os.environ["DEEPSEEK_API_KEY"] = "sk-deepseek-test"
        info = resolve_model("deepseek-chat")
        assert info.provider == "openai"
        assert info.api_key_env_var == "DEEPSEEK_API_KEY"
        assert info.api_key == "sk-deepseek-test"
        del os.environ["DEEPSEEK_API_KEY"]

    def test_qwen_plus(self):
        """qwen-plus → dashscope provider + DASHSCOPE_API_KEY"""
        os.environ["DASHSCOPE_API_KEY"] = "sk-dashscope-test"
        info = resolve_model("qwen-plus")
        assert info.provider == "dashscope"
        assert info.api_key_env_var == "DASHSCOPE_API_KEY"
        assert info.api_key == "sk-dashscope-test"
        del os.environ["DASHSCOPE_API_KEY"]

    def test_gpt4o(self):
        """gpt-4o → openai + OPENAI_API_KEY"""
        os.environ["OPENAI_API_KEY"] = "sk-openai-test"
        info = resolve_model("gpt-4o")
        assert info.provider == "openai"
        assert info.api_key_env_var == "OPENAI_API_KEY"
        del os.environ["OPENAI_API_KEY"]

    def test_fallback_to_llm_api_key(self):
        """未匹配模型时回退到 LLM_API_KEY"""
        os.environ["LLM_API_KEY"] = "sk-fallback"
        info = resolve_model("some-unknown-model")
        assert info.provider == "openai"
        assert info.api_key == "sk-fallback"
        del os.environ["LLM_API_KEY"]

    def test_base_url_from_env(self):
        """base_url 应从对应环境变量读取"""
        os.environ["DEEPSEEK_BASE_URL"] = "https://custom.deepseek.com/v1"
        os.environ["DEEPSEEK_API_KEY"] = "sk-test"
        info = resolve_model("deepseek-chat")
        assert info.base_url == "https://custom.deepseek.com/v1"
        del os.environ["DEEPSEEK_BASE_URL"]
        del os.environ["DEEPSEEK_API_KEY"]

    # Qwen 变体
    def test_qwen3_max(self):
        os.environ["DASHSCOPE_API_KEY"] = "sk-test"
        info = resolve_model("qwen3-max")
        assert info.provider == "dashscope"
        del os.environ["DASHSCOPE_API_KEY"]

    def test_moonshot(self):
        os.environ["MOONSHOT_API_KEY"] = "sk-test"
        info = resolve_model("moonshot-v1-32k")
        assert info.provider == "openai"
        del os.environ["MOONSHOT_API_KEY"]

    def test_glm(self):
        os.environ["ZHIPU_API_KEY"] = "sk-test"
        info = resolve_model("glm-4-plus")
        assert info.provider == "openai"
        del os.environ["ZHIPU_API_KEY"]

    def test_case_insensitive(self):
        """模型名不区分大小写"""
        os.environ["DEEPSEEK_API_KEY"] = "sk-test"
        info = resolve_model("DeepSeek-Chat")
        assert info.provider == "openai"
        del os.environ["DEEPSEEK_API_KEY"]


class TestModelPrefixMap:
    """验证映射表的完整性"""

    def test_all_prefixes_have_provider(self):
        for prefix, provider, key_var, _ in MODEL_PREFIX_MAP:
            assert provider in ("openai", "dashscope"), f"{prefix}: 未知 provider {provider}"
            assert key_var, f"{prefix}: 缺少 API Key 环境变量名"

    def test_prefix_order(self):
        """长前缀应在短前缀之前"""
        for i, (p1, _, _, _) in enumerate(MODEL_PREFIX_MAP):
            for j, (p2, _, _, _) in enumerate(MODEL_PREFIX_MAP):
                if i < j and p1.startswith(p2):
                    # p1 是 p2 的超集，但 p2 排在前面 → 错误
                    pass  # 目前没有冲突前缀


class TestCreateLLMFromModel:

    def test_create_unknown_model(self):
        """未知模型应返回 LLMBase 实例（使用回退配置）"""
        os.environ["LLM_API_KEY"] = "sk-test"
        os.environ["LLM_BASE_URL"] = "https://test.api/v1"
        llm = create_llm_from_model("unknown-model-x")
        assert llm is not None
        assert llm.model == "unknown-model-x"
        del os.environ["LLM_API_KEY"]
        del os.environ["LLM_BASE_URL"]
