"""
钉钉 API 客户端

封装钉钉的消息发送能力，支持：
- 通过企业内部应用机器人发消息（单聊/群聊）
- 通过 Webhook 向群机器人发消息（快速测试）

钉钉文档：
- 获取 Token: https://open.dingtalk.com/document/orgapp/obtain-orgapp-token
- 机器人消息: https://open.dingtalk.com/document/orgapp/robot-message-data-types
"""
import json
import logging
import time
from typing import Optional

import httpx

from ticket_agent.integrations.dingtalk.config import get_config

logger = logging.getLogger(__name__)

# Token 缓存
_token_cache: dict = {
    "access_token": None,
    "expires_at": 0,
}


async def get_access_token() -> str:
    """
    获取钉钉企业内部应用 Access Token（带缓存）。

    文档：https://open.dingtalk.com/document/orgapp/obtain-orgapp-token
    有效期 7200 秒，提前 60 秒刷新。
    """
    now = time.time()
    if _token_cache["access_token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]

    config = get_config()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{config.base_url}/gettoken",
            params={
                "appkey": config.app_key,
                "appsecret": config.app_secret,
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("errcode") != 0:
            raise RuntimeError(f"获取钉钉 Token 失败: {data.get('errmsg', data)}")

        _token_cache["access_token"] = data["access_token"]
        _token_cache["expires_at"] = now + data.get("expires_in", 7200)
        logger.info("钉钉 Access Token 已刷新")
        return data["access_token"]


async def send_text_message(
    userid: str,
    text: str,
    robot_code: Optional[str] = None,
) -> bool:
    """
    向用户发送文本消息（单聊）。

    文档：https://open.dingtalk.com/document/orgapp/robot-message-data-types

    Args:
        userid: 接收消息的用户 ID（可在钉钉后台查看）
        text: 消息内容
        robot_code: 机器人编码（可选）

    Returns:
        是否发送成功
    """
    token = await get_access_token()
    config = get_config()

    body = {
        "robotCode": robot_code or "",
        "userIds": [userid],
        "msgKey": "sampleText",
        "msgParam": json.dumps({"content": text}, ensure_ascii=False),
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{config.base_url}/v1.0/robot/oToMessages/batchSend",
            headers={
                "x-acs-dingtalk-access-token": token,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=10,
        )
        if resp.status_code == 200:
            return True

        logger.error(f"钉钉发送消息失败: status={resp.status_code} body={resp.text[:200]}")
        return False


async def send_markdown_message(
    userid: str,
    title: str,
    text: str,
    robot_code: Optional[str] = None,
) -> bool:
    """
    向用户发送 Markdown 消息（单聊）。

    文档：https://open.dingtalk.com/document/orgapp/robot-message-data-types

    Args:
        userid: 接收消息的用户 ID
        title: 消息标题
        text: Markdown 格式的消息内容
        robot_code: 机器人编码（可选）

    Returns:
        是否发送成功
    """
    token = await get_access_token()
    config = get_config()

    body = {
        "robotCode": robot_code or "",
        "userIds": [userid],
        "msgKey": "sampleMarkdown",
        "msgParam": json.dumps({
            "title": title,
            "text": text,
        }, ensure_ascii=False),
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{config.base_url}/v1.0/robot/oToMessages/batchSend",
            headers={
                "x-acs-dingtalk-access-token": token,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=10,
        )
        if resp.status_code == 200:
            return True

        logger.error(f"钉钉发送 Markdown 失败: status={resp.status_code} body={resp.text[:200]}")
        return False


async def send_webhook_message(text: str) -> bool:
    """
    通过 Webhook 向群机器人发送消息（快速测试用）。

    配置方式：在钉钉群中创建自定义机器人，获取 Webhook URL 中的 access_token。

    Args:
        text: 消息内容

    Returns:
        是否发送成功
    """
    config = get_config()
    if not config.webhook_token:
        logger.error("钉钉 Webhook 模式未配置（缺少 DINGTALK_WEBHOOK_TOKEN）")
        return False

    webhook_url = f"{config.base_url}/robot/send?access_token={config.webhook_token}"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            webhook_url,
            json={
                "msgtype": "text",
                "text": {"content": text},
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("errcode") == 0:
            logger.info("钉钉 Webhook 消息发送成功")
            return True

        logger.error(f"钉钉 Webhook 发送失败: {data.get('errmsg', data)}")
        return False
