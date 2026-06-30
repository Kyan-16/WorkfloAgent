"""
企业微信配置
"""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class WecomConfig:
    """企业微信应用配置"""
    corp_id: str = ""              # 企业 ID（在企微后台 -> 我的企业 -> 企业信息）
    agent_id: str = ""             # 应用 AgentId（自建应用 -> 基础信息）
    agent_secret: str = ""         # 应用 Secret
    token: str = ""                # 回调 Token（用于验证回调 URL）
    encoding_aes_key: str = ""     # 回调 EncodingAESKey（消息加解密）
    webhook_key: str = ""          # 群机器人 Webhook key（快速测试用）
    base_url: str = "https://qyapi.weixin.qq.com"

    @classmethod
    def from_env(cls) -> "WecomConfig":
        return cls(
            corp_id=os.getenv("WECOM_CORP_ID", ""),
            agent_id=os.getenv("WECOM_AGENT_ID", ""),
            agent_secret=os.getenv("WECOM_AGENT_SECRET", ""),
            token=os.getenv("WECOM_TOKEN", ""),
            encoding_aes_key=os.getenv("WECOM_ENCODING_AES_KEY", ""),
            webhook_key=os.getenv("WECOM_WEBHOOK_KEY", ""),
        )

    @property
    def enabled(self) -> bool:
        """完整模式：需要 corp_id + agent_secret"""
        return bool(self.corp_id and self.agent_secret)

    @property
    def webhook_enabled(self) -> bool:
        """Webhook 模式：只需 webhook_key"""
        return bool(self.webhook_key)


_config: Optional[WecomConfig] = None


def get_config() -> WecomConfig:
    global _config
    if _config is None:
        _config = WecomConfig.from_env()
    return _config


def reset_wecom_config():
    global _config
    _config = None


def set_config(cfg: WecomConfig):
    global _config
    _config = cfg
