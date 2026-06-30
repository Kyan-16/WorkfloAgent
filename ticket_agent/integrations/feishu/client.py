"""
飞书 API 客户端

封装飞书开放平台的认证和消息发送能力。
"""
import json
import logging
import time
from typing import Optional

import httpx

from ticket_agent.integrations.feishu.config import get_config

logger = logging.getLogger(__name__)

# Token 缓存
_token_cache: dict = {
    "access_token": None,
    "expires_at": 0,
}


async def _get_tenant_access_token() -> str:
    """
    获取 tenant_access_token（带缓存）

    飞书文档：https://open.feishu.cn/document/server-docs/authentication-management/access-token/tenant_access_token_internal
    """
    now = time.time()
    if _token_cache["access_token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]

    config = get_config()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{config.base_url}/open-apis/auth/v3/tenant_access_token/internal",
            json={
                "app_id": config.app_id,
                "app_secret": config.app_secret,
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"获取 tenant_access_token 失败: {data.get('msg', data)}")

        _token_cache["access_token"] = data["tenant_access_token"]
        _token_cache["expires_at"] = now + data.get("expire", 7200)
        logger.info("已刷新飞书 tenant_access_token")
        return _token_cache["access_token"]


async def send_text_message(open_id: str, text: str) -> dict:
    """
    向飞书用户发送文本消息

    Args:
        open_id: 用户的 open_id
        text: 消息文本内容

    Returns:
        飞书 API 响应
    """
    token = await _get_tenant_access_token()
    config = get_config()

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{config.base_url}/open-apis/im/v1/messages",
            params={"receive_id_type": "open_id"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "receive_id": open_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.error(f"发送飞书消息失败: {data.get('msg', data)}")
        return data


async def send_card_message(open_id: str, title: str, body: str, note: str = "") -> dict:
    """
    向飞书用户发送卡片消息（更美观的展示）

    Args:
        open_id: 用户的 open_id
        title: 卡片标题
        body: 卡片正文
        note: 备注信息

    Returns:
        飞书 API 响应
    """
    token = await _get_tenant_access_token()
    config = get_config()

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "blue",
        },
        "elements": [
            {
                "tag": "markdown",
                "content": body,
            },
        ],
    }

    if note:
        card["elements"].append({
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": note}],
        })

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{config.base_url}/open-apis/im/v1/messages",
            params={"receive_id_type": "open_id"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={
                "receive_id": open_id,
                "msg_type": "interactive",
                "content": json.dumps(card, ensure_ascii=False),
            },
            timeout=10,
        )
        data = resp.json()
        if data.get("code") != 0:
            logger.error(f"发送飞书卡片消息失败: {data.get('msg', data)}")
        return data
