"""
配置加载器 - 支持 YAML 文件 + 环境变量覆盖

加载优先级（从低到高）：
  1. dataclass 默认值
  2. settings.yaml
  3. settings.{env}.yaml
  4. 环境变量（AGENT_ 前缀）
"""
import os
import yaml
from pathlib import Path
from dataclasses import fields
from typing import Optional, get_args, get_origin

from .settings import (
    Settings, LLMConfig, RAGConfig, MemoryConfig, ServerConfig,
    AgentConfig, EmbeddingConfig, CrossEncoderConfig, MonitoringConfig, StorageConfig,
)

# 配置段到 dataclass 的映射
_SECTION_CLASSES = {
    "llm": LLMConfig,
    "rag": RAGConfig,
    "agent": AgentConfig,
    "embedding": EmbeddingConfig,
    "cross_encoder": CrossEncoderConfig,
    "monitoring": MonitoringConfig,
    "storage": StorageConfig,
    "memory": MemoryConfig,
    "server": ServerConfig,
}


class ConfigLoader:
    """配置加载器"""

    def __init__(self, config_dir: Optional[str] = None):
        self.config_dir = Path(config_dir) if config_dir else Path("config")

    def load(self, env: Optional[str] = None) -> Settings:
        env = env or os.getenv("AGENT_ENV", "development")
        base_data = self._load_yaml("settings.yaml")
        env_data = self._load_yaml(f"settings.{env}.yaml")
        merged = self._deep_merge(base_data, env_data)
        merged = self._apply_env_overrides(merged)
        return self._build_settings(merged, env)

    def _load_yaml(self, filename: str) -> dict:
        filepath = self.config_dir / filename
        if not filepath.exists():
            return {}
        with open(filepath, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> dict:
        """深度合并字典（不可变）"""
        import copy
        result = copy.deepcopy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ConfigLoader._deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result

    @staticmethod
    def _apply_env_overrides(data: dict) -> dict:
        prefix = "AGENT_"
        for key, value in os.environ.items():
            if not key.startswith(prefix):
                continue
            parts = key[len(prefix):].lower().split("_", 1)
            if len(parts) == 2:
                section, field = parts[0], parts[1]
                if section not in data:
                    data[section] = {}
                data[section][field] = value
            elif len(parts) == 1:
                data[parts[0]] = value
        return data

    @staticmethod
    def _build_settings(data: dict, env: str) -> Settings:
        kwargs = {
            "app_name": data.get("app_name", "WorkfloAgent"),
            "version": data.get("version", "1.0.0"),
            "env": env,
            "prompts_dir": data.get("prompts_dir", "prompts"),
            "log_level": data.get("log_level", "INFO"),
        }
        for section, cls in _SECTION_CLASSES.items():
            section_data = data.get(section, {})
            kwargs[section] = cls(**ConfigLoader._coerce_dataclass_values(cls, section_data))
        return Settings(**kwargs)

    @staticmethod
    def _coerce_dataclass_values(cls, data: dict) -> dict:
        field_map = {f.name: f for f in fields(cls)}
        result = {}
        for key, value in data.items():
            field_info = field_map.get(key)
            if not field_info:
                continue
            result[key] = ConfigLoader._coerce_value(value, field_info.type)
        return result

    @staticmethod
    def _coerce_value(value, target_type):
        if not isinstance(value, str):
            return value
        origin = get_origin(target_type)
        args = get_args(target_type)
        if origin is Optional:
            target_type = args[0]
        elif origin is list:
            return [item.strip() for item in value.split(",") if item.strip()]
        elif args and type(None) in args:
            target_type = next((arg for arg in args if arg is not type(None)), str)
        if target_type is bool:
            return value.lower() in ("1", "true", "yes", "on")
        if target_type is int:
            return int(value)
        if target_type is float:
            return float(value)
        return value


_settings_cache: Optional[Settings] = None


def get_settings(config_dir: Optional[str] = None) -> Settings:
    global _settings_cache
    if _settings_cache is None:
        _settings_cache = ConfigLoader(config_dir).load()
    return _settings_cache


def reload_settings(config_dir: Optional[str] = None) -> Settings:
    global _settings_cache
    _settings_cache = ConfigLoader(config_dir).load()
    return _settings_cache
