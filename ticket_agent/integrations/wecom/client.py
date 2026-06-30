"""
企业微信 API 客户端

封装企业微信的认证和消息发送能力。
"""
import json
import logging
import time
from typing import Optional

import httpx

from ticket_agent.integrations.wecom.config import get_config

logger = logging.getLogger(__name__)

# Token 缓存
_token_cache: dict = {
    "access_token": None,
    "expires_at": 0,
}


async def get_access_token() -> str:
    """
    获取企业微信 Access Token（带缓存）

    企业微信文档：https://developer.work.weixin.qq.com/document/path/91039
    有效期 7200 秒，提前 60 秒刷新。
    """
    now = time.time()
    if _token_cache["access_token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]

    config = get_config()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{config.base_url}/cgi-bin/gettoken",
            params={
                "corpid": config.corp_id,
                "corpsecret": config.agent_secret,
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("errcode") != 0:
            raise RuntimeError(f"获取 access_token 失败: {data.get('errmsg', data)}")

        _token_cache["access_token"] = data["access_token"]
        _token_cache["expires_at"] = now + data.get("expires_in", 7200)
        logger.info("已刷新企业微信 Access Token")
        return _token_cache["access_token"]


def _ensure_user_ids(user_id: str | list[str]) -> str:
    """确保 user_id 是 '|' 分隔的字符串"""
    if isinstance(user_id, list):
        return "|".join(user_id)
    return user_id


async def send_text_message(user_id: str | list[str], content: str) -> dict:
    """
    向企业微信用户发送文本消息

    Args:
        user_id: 用户 ID 或 ID 列表
        content: 消息内容

    Returns:
        企业微信 API 响应
    """
    token = await get_access_token()
    config = get_config()

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{config.base_url}/cgi-bin/message/send",
            params={"access_token": token},
            json={
                "touser": _ensure_user_ids(user_id),
                "msgtype": "text",
                "agentid": int(config.agent_id) if config.agent_id else 0,
                "text": {"content": content},
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("errcode") != 0:
            logger.error(f"发送企业微信消息失败: {data.get('errmsg', data)}")
        else:
            logger.info(f"企业微信消息已发送: touser={user_id}")
        return data


async def send_card_message(user_id: str | list[str], title: str, description: str, url: str = "") -> dict:
    """
    向企业微信用户发送卡片消息（图文链接样式）

    使用 news 消息类型，展示工单处理结果。
    """
    token = await get_access_token()
    config = get_config()

    articles = [{
        "title": title,
        "description": description[:500],
        "url": url or "",
    }]

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{config.base_url}/cgi-bin/message/send",
            params={"access_token": token},
            json={
                "touser": _ensure_user_ids(user_id),
                "msgtype": "news",
                "agentid": int(config.agent_id) if config.agent_id else 0,
                "news": {"articles": articles},
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("errcode") != 0:
            logger.error(f"发送企业微信卡片消息失败: {data.get('errmsg', data)}")
        return data


async def send_webhook_message(key: str, content: str) -> dict:
    """
    通过 Webhook 地址向企业微信群发送消息

    不需要应用配置，只需要 Webhook URL 的 key。
    """
    url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            json={
                "msgtype": "text",
                "text": {"content": content},
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("errcode") != 0:
            logger.error(f"企业微信群机器人发送失败: {data.get('errmsg', data)}")
        return data
