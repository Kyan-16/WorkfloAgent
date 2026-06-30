"""
钉钉机器人事件处理

处理钉钉机器人回调：
- GET  /api/dingtalk/callback: URL 验证
- POST /api/dingtalk/callback: 消息回调

工作流程：
  用户在钉钉向机器人发消息
    → 钉钉回调 POST /api/dingtalk/callback
    → 解析消息内容和发送者
    → 调用 Coordinator 处理工单
    → 通过钉钉 API 回复用户

钉钉文档：https://open.dingtalk.com/document/orgapp/robot-overview
"""
import hashlib
import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse

from ticket_agent.integrations.dingtalk.config import get_config
from ticket_agent.integrations.dingtalk.client import send_text_message, send_markdown_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dingtalk", tags=["钉钉集成"])

_coordinator = None


def set_coordinator(coordinator):
    global _coordinator
    _coordinator = coordinator


def get_coordinator():
    if _coordinator is None:
        raise HTTPException(status_code=503, detail="Coordinator 未初始化")
    return _coordinator


# ─── 回调处理 ───


@router.get("/callback", summary="钉钉 URL 验证")
async def verify_url():
    """
    钉钉在配置回调 URL 时会发送 GET 请求验证地址有效性。
    返回 "success" 即可通过验证。
    """
    return PlainTextResponse("success")


@router.post("/callback", summary="钉钉消息回调")
async def handle_callback(request: Request):
    """
    处理钉钉机器人消息回调。

    当用户在钉钉中@机器人或给机器人发私信时，
    钉钉会向此地址发送 POST 请求。
    """
    config = get_config()
    if not config.enabled:
        raise HTTPException(status_code=400, detail="钉钉集成未启用")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="无效的请求体")

    logger.debug(f"钉钉回调: {json.dumps(body, ensure_ascii=False)[:200]}")

    # 钉钉回调格式：{"senderId": "...", "conversationId": "...", "chatbotUserId": "...", "msgtype": "text", "text": {"content": "..."}, "msgId": "..."}
    # 注意：不同的回调事件类型，数据结构不同
    # 这里处理 im 机器人消息回调

    sender_id = body.get("senderId") or body.get("sender", {}).get("senderId", "")
    msg_type = body.get("msgtype", "text")
    conversation_id = body.get("conversationId", "")
    msg_id = body.get("msgId", "") or body.get("msgid", "")

    # 解析消息内容
    text = ""
    if msg_type == "text":
        text = body.get("text", {}).get("content", "").strip()
    elif msg_type == "markdown":
        text = body.get("markdown", {}).get("text", "").strip()

    if not text:
        logger.info(f"收到钉钉消息但内容为空 (msgType={msg_type})")
        return JSONResponse({"success": True})

    # 去掉 @机器人的部分（格式：@机器人名 消息内容）
    if "@" in text:
        # 找到第一个空格后的内容
        parts = text.split(" ", 1)
        if len(parts) > 1:
            text = parts[1].strip()

    if not text:
        return JSONResponse({"success": True})

    logger.info(f"钉钉消息来自 {sender_id}: {text[:50]}...")

    # 处理工单
    try:
        coordinator = get_coordinator()
        result = await coordinator.process(
            user_input=text,
            user_id=f"dingtalk_{sender_id}",
            session_id=f"dingtalk_{sender_id}",
        )

        # 构建回复
        response_text = result.get("response", "")
        if not response_text:
            response_text = f"已收到您的工单（编号：{result.get('ticket_id', '')}），我们将尽快处理。"

        # 发送回复
        success = await send_markdown_message(
            userid=sender_id,
            title="工单处理结果",
            text=f"### 工单处理结果\n\n{response_text}\n\n---\n*工单编号：{result.get('ticket_id', '')}*",
        )

        if success:
            logger.info(f"钉钉回复成功: {result.get('ticket_id', '')}")
        else:
            # 降级到文本消息
            await send_text_message(sender_id, response_text[:200])

    except Exception as e:
        logger.error(f"钉钉工单处理失败: {e}", exc_info=True)
        try:
            await send_text_message(sender_id, "系统处理异常，请稍后重试或联系管理员。")
        except Exception:
            pass

    return JSONResponse({"success": True})
