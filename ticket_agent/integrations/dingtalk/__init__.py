"""
钉钉集成模块

实现钉钉机器人与企业工单 Agent 的对接：
1. 用户在钉钉中向机器人发消息
2. 服务端接收钉钉回调
3. 调用 Coordinator 处理工单
4. 通过钉钉 API 回复用户

使用方式：
    # 启动服务
    uvicorn ticket_agent.main:app --reload --port 8000

    # 设置钉钉配置（环境变量）
    export DINGTALK_APP_KEY=dingxxxxxxxxxxxx
    export DINGTALK_APP_SECRET=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

    # 配置钉钉机器人的消息接收地址
    # 钉钉开放平台 → 应用开发 → 企业内部应用 → 机器人 → 消息接收模式
    # 选择 HTTP 模式，回调地址填写: https://your-domain/api/dingtalk/callback
"""
from ticket_agent.integrations.dingtalk.config import DingTalkConfig, get_config, set_config
from ticket_agent.integrations.dingtalk.client import (
    get_access_token,
    send_text_message,
    send_markdown_message,
    send_webhook_message,
)
from ticket_agent.integrations.dingtalk.bot import router, set_coordinator

__all__ = [
    "DingTalkConfig",
    "get_config",
    "set_config",
    "get_access_token",
    "send_text_message",
    "send_markdown_message",
    "send_webhook_message",
    "router",
    "set_coordinator",
]
