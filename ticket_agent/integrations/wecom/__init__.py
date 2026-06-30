"""
企业微信集成
"""
from ticket_agent.integrations.wecom.config import WecomConfig, get_config, set_config
from ticket_agent.integrations.wecom.client import (
    get_access_token,
    send_text_message,
    send_card_message,
    send_webhook_message,
)
from ticket_agent.integrations.wecom.bot import router, set_coordinator

__all__ = [
    "WecomConfig",
    "get_config",
    "set_config",
    "get_access_token",
    "send_text_message",
    "send_card_message",
    "send_webhook_message",
    "router",
    "set_coordinator",
]
