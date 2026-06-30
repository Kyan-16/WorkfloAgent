"""
配置加载器 单元测试
"""
import os
import tempfile
from pathlib import Path

import pytest
import yaml

from config.loader import ConfigLoader
from config.settings import Settings


def test_deep_merge():
    """测试深度合并不变性"""
    base = {"llm": {"api_key": "old", "model": "gpt-4", "temperature": 0.7}}
    override = {"llm": {"api_key": "new"}}

    result = ConfigLoader._deep_merge(base, override)

    # 验证合并结果
    assert result["llm"]["api_key"] == "new"
    assert result["llm"]["model"] == "gpt-4"
    assert result["llm"]["temperature"] == 0.7

    # 验证原数据未被修改（不可变性）
    assert base["llm"]["api_key"] == "old"
    assert base["llm"]["temperature"] == 0.7


def test_deep_merge_nested():
    """测试深层嵌套合并"""
    base = {"rag": {"qdrant": {"host": "localhost", "port": 6333}}}
    override = {"rag": {"qdrant": {"port": 6334}}}

    result = ConfigLoader._deep_merge(base, override)
    assert result["rag"]["qdrant"]["host"] == "localhost"
    assert result["rag"]["qdrant"]["port"] == 6334


def test_deep_merge_new_key():
    """测试新增键"""
    base = {"llm": {"api_key": "old"}}
    override = {"memory": {"type": "redis"}}

    result = ConfigLoader._deep_merge(base, override)
    assert result["llm"]["api_key"] == "old"
    assert result["memory"]["type"] == "redis"


def test_coerce_bool():
    """测试布尔值类型转换"""
    assert ConfigLoader._coerce_value("true", bool) is True
    assert ConfigLoader._coerce_value("True", bool) is True
    assert ConfigLoader._coerce_value("1", bool) is True
    assert ConfigLoader._coerce_value("yes", bool) is True
    assert ConfigLoader._coerce_value("false", bool) is False
    assert ConfigLoader._coerce_value("0", bool) is False


def test_coerce_int():
    """测试整数类型转换"""
    assert ConfigLoader._coerce_value("42", int) == 42
    assert ConfigLoader._coerce_value("0", int) == 0
    assert ConfigLoader._coerce_value("-1", int) == -1


def test_coerce_float():
    """测试浮点数类型转换"""
    assert ConfigLoader._coerce_value("3.14", float) == 3.14
    assert ConfigLoader._coerce_value("0.0", float) == 0.0


def test_coerce_non_string():
    """测试非字符串值直接返回"""
    assert ConfigLoader._coerce_value(42, str) == 42
    assert ConfigLoader._coerce_value(True, bool) is True


def test_load_yaml_not_exists():
    """测试加载不存在的 YAML 文件返回空字典"""
    loader = ConfigLoader(config_dir="/nonexistent/path")
    result = loader._load_yaml("nonexistent.yaml")
    assert result == {}


def test_build_settings_defaults():
    """测试从空字典构建 Settings 使用默认值"""
    settings = ConfigLoader._build_settings({}, env="production")
    assert isinstance(settings, Settings)
    assert settings.env == "production"
    assert settings.version == "1.0.0"


def test_build_settings_with_data():
    """测试从字典构建 Settings"""
    data = {
        "app_name": "TestApp",
        "llm": {
            "provider": "openai",
            "model": "gpt-4",
            "api_key": "sk-test",
            "temperature": 0.5,
        },
        "agent": {
            "max_tool_rounds": 10,
            "use_langgraph": True,
        },
    }
    settings = ConfigLoader._build_settings(data, env="test")
    assert settings.app_name == "TestApp"
    assert settings.llm.provider == "openai"
    assert settings.llm.model == "gpt-4"
    assert settings.llm.temperature == 0.5
    assert settings.agent.max_tool_rounds == 10
    assert settings.agent.use_langgraph is True
