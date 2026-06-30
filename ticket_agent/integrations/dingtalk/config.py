"""
钉钉配置

对接钉钉企业内部应用机器人：
https://open.dingtalk.com/document/orgapp/robot-overview

配置方式（环境变量）：
    DINGTALK_APP_KEY=dingxxxxxxxxxxxx
    DINGTALK_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    DINGTALK_WEBHOOK_TOKEN=xxx              # 群机器人 Webhook access_token（可选，快速测试用）
"""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class DingTalkConfig:
    """钉钉应用配置"""
    app_key: str = ""                # 应用的 AppKey
    app_secret: str = ""             # 应用的 AppSecret
    webhook_token: str = ""          # 群机器人 Webhook access_token（可选）
    base_url: str = "https://oapi.dingtalk.com"

    @classmethod
    def from_env(cls) -> "DingTalkConfig":
        return cls(
            app_key=os.getenv("DINGTALK_APP_KEY", ""),
            app_secret=os.getenv("DINGTALK_APP_SECRET", ""),
            webhook_token=os.getenv("DINGTALK_WEBHOOK_TOKEN", ""),
        )

    @property
    def enabled(self) -> bool:
        """完整模式：需要 app_key + app_secret"""
        return bool(self.app_key and self.app_secret)

    @property
    def webhook_enabled(self) -> bool:
        """Webhook 模式：只需 webhook_token"""
        return bool(self.webhook_token)


_config: Optional[DingTalkConfig] = None


def get_config() -> DingTalkConfig:
    global _config
    if _config is None:
        _config = DingTalkConfig.from_env()
    return _config


def reset_config():
    global _config
    _config = None


def set_config(cfg: DingTalkConfig):
    global _config
    _config = cfg
