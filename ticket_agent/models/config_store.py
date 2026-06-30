"""
模型配置持久化存储

将用户在界面上选择的模型配置保存到 data/model_config.json，
重启后自动加载。API Key 使用 Fernet 对称加密存储。

首次使用时自动生成加密密钥，可通过 MODEL_CONFIG_KEY 环境变量固定。
"""
import json
import os
import base64
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

CONFIG_DIR = Path("data")
CONFIG_FILE = CONFIG_DIR / "model_config.json"
KEY_FILE = CONFIG_DIR / ".model_config_key"


def _get_fernet():
    """获取 Fernet 加密器，密钥来自环境变量或自动生成的文件。"""
    from cryptography.fernet import Fernet
    from cryptography.fernet import InvalidToken

    env_key = os.getenv("MODEL_CONFIG_KEY")
    if env_key:
        try:
            return Fernet(env_key.encode("utf-8") if isinstance(env_key, str) else env_key), InvalidToken
        except Exception:
            pass

    if KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    else:
        key = Fernet.generate_key().decode("utf-8")
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        KEY_FILE.write_text(key, encoding="utf-8")
        logger.info(f"已生成模型配置加密密钥: {KEY_FILE}（设置 MODEL_CONFIG_KEY 环境变量可固定）")
    return Fernet(key.encode("utf-8")), InvalidToken


def _encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    f, _ = _get_fernet()
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def _decrypt(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    f, err = _get_fernet()
    try:
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except err:
        return ciphertext


@dataclass
class ModelConfig:
    """用户保存的模型配置"""
    provider_id: str = "deepseek"       # Provider ID
    model: str = "deepseek-chat"        # 模型名
    api_key: str = ""                   # API Key（保存时建议做环境变量引用）
    base_url: str = ""                  # API 地址（可选）
    label: str = "DeepSeek"             # 显示名称
    is_active: bool = True              # 是否为当前使用的配置


class ModelConfigStore:
    """模型配置持久化存储"""

    def __init__(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    def load_all(self) -> list[ModelConfig]:
        """读取所有已保存的配置"""
        if not CONFIG_FILE.exists():
            return []

        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            configs = []
            for item in data:
                if item.get("api_key"):
                    item["api_key"] = _decrypt(item["api_key"])
                configs.append(ModelConfig(**item))
            return configs
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"模型配置文件解析失败: {e}")
            return []

    def save_all(self, configs: list[ModelConfig]):
        """保存所有配置（API Key 自动加密）"""
        data = []
        for c in configs:
            d = asdict(c)
            if d.get("api_key"):
                d["api_key"] = _encrypt(d["api_key"])
            data.append(d)
        CONFIG_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(f"模型配置已保存 ({len(configs)} 个)")

    def get_active(self) -> Optional[ModelConfig]:
        """获取当前激活的配置"""
        for c in self.load_all():
            if c.is_active:
                return c
        return None

    def set_active(self, provider_id: str):
        """设置某个配置为激活状态"""
        configs = self.load_all()
        found = False
        for c in configs:
            if c.provider_id == provider_id:
                c.is_active = True
                found = True
            else:
                c.is_active = False
        if found:
            self.save_all(configs)

    def upsert(self, config: ModelConfig):
        """添加或更新配置"""
        configs = self.load_all()
        for i, c in enumerate(configs):
            if c.provider_id == config.provider_id:
                configs[i] = config
                break
        else:
            configs.append(config)
        self.save_all(configs)

    def delete(self, provider_id: str) -> bool:
        """删除配置"""
        configs = self.load_all()
        new_configs = [c for c in configs if c.provider_id != provider_id]
        if len(new_configs) == len(configs):
            return False
        self.save_all(new_configs)
        return True

    def apply_config(self, config: ModelConfig) -> str:
        """
        将配置应用到运行时。

        设置环境变量并调用 /switch_model 的逻辑，
        使配置立即生效。

        Returns:
            结果消息
        """
        from llm.provider_map import resolve_model
        from llm.factory import create_llm

        # 先解析模型名，获取 provider 信息
        info = resolve_model(config.model)
        actual_provider = info.provider

        # 创建 LLM 实例
        llm_config = {
            "provider": actual_provider,
            "model": config.model,
            "api_key": config.api_key,
        }
        if config.base_url:
            llm_config["base_url"] = config.base_url

        llm = create_llm(llm_config)

        # 获取 coordinator 并应用
        from ticket_agent.api.deps import get_coordinator
        coord = get_coordinator()

        coord.llm = llm
        coord.classifier.llm = llm
        coord.executor.llm = llm

        # 更新 ConfigStore 状态
        self.upsert(config)
        self.set_active(config.provider_id)

        return f"模型已切换至 {config.label} ({config.model})"


# 全局单例
_store: Optional[ModelConfigStore] = None


def get_model_config_store() -> ModelConfigStore:
    global _store
    if _store is None:
        _store = ModelConfigStore()
    return _store
