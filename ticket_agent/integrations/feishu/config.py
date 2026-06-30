"""
飞书配置
"""
import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FeishuConfig:
    """飞书应用配置"""

    app_id: str = ""
    app_secret: str = ""

    # API 基础地址
    base_url: str = "https://open.feishu.cn"

    # 事件回调验证 token（在飞书开发者后台配置）
    verification_token: str = ""

    # 加密 key（如开启了加密）
    encrypt_key: str = ""

    @classmethod
    def from_env(cls) -> "FeishuConfig":
        """从环境变量加载配置"""
        return cls(
            app_id=os.getenv("FEISHU_APP_ID", ""),
            app_secret=os.getenv("FEISHU_APP_SECRET", ""),
            verification_token=os.getenv("FEISHU_VERIFICATION_TOKEN", ""),
            encrypt_key=os.getenv("FEISHU_ENCRYPT_KEY", ""),
            base_url=os.getenv("FEISHU_BASE_URL", "https://open.feishu.cn"),
        )

    @property
    def enabled(self) -> bool:
        """是否配置了飞书集成"""
        return bool(self.app_id and self.app_secret)


# 全局配置实例
_config: Optional[FeishuConfig] = None


def get_config() -> FeishuConfig:
    global _config
    if _config is None:
        _config = FeishuConfig.from_env()
    return _config


def reset_feishu_config():
    global _config
    _config = None


def set_config(cfg: FeishuConfig):
    global _config
    _config = cfg
