"""
飞书机器人事件处理

处理飞书事件回调：
- GET /event: 飞书 URL 验证
- POST /event: 事件回调（含消息事件）
"""
import hmac
import hashlib
import base64
import json
import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from ticket_agent.integrations.feishu.config import get_config
from ticket_agent.integrations.feishu.client import send_text_message, send_card_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/feishu", tags=["飞书集成"])

# 注入 coordinator 用于处理工单
_coordinator = None


def set_coordinator(coordinator):
    global _coordinator
    _coordinator = coordinator


def get_coordinator():
    if _coordinator is None:
        raise HTTPException(status_code=503, detail="Coordinator 未初始化")
    return _coordinator


def _decrypt(data: str, encrypt_key: str) -> str:
    """AES 解密飞书加密消息（如开启了 encrypt_key）"""
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        key_bytes = hashlib.sha256(encrypt_key.encode()).digest()
        encrypted = base64.b64decode(data)
        nonce = encrypted[:12]
        ciphertext = encrypted[12:-16]
        tag = encrypted[-16:]
        cipher = Cipher(algorithms.AES(key_bytes), modes.GCM(nonce, tag))
        decryptor = cipher.decryptor()
        return decryptor.update(ciphertext) + decryptor.finalize()
    except Exception as e:
        logger.error(f"飞书消息解密失败: {e}")
        return ""


def _parse_message_content(message_type: str, content_str: str) -> str:
    """
    解析飞书消息内容

    不同消息类型的 content 格式不同：
    - text: {"text": "hello"}
    - post: {"zh_cn": {"content": [[{"tag": "text", "text": "hello"}]]}}
    """
    try:
        content = json.loads(content_str)
        if message_type == "text":
            return content.get("text", "").strip()
        elif message_type == "post":
            post = content.get("zh_cn", {})
            paragraphs = post.get("content", [])
            texts = []
            for para in paragraphs:
                for segment in para:
                    if segment.get("tag") == "text":
                        texts.append(segment.get("text", ""))
            return "".join(texts).strip()
    except (json.JSONDecodeError, AttributeError):
        return content_str or ""
    return ""


async def _handle_message_event(event: dict):
    """
    处理 im.message.receive_v1 事件

    流程：
    1. 解析消息内容和发送者
    2. 调用 Coordinator 处理工单
    3. 将结果通过飞书 API 回复
    """
    sender = event.get("sender", {})
    message = event.get("message", {})

    open_id = sender.get("sender_id", {}).get("open_id", "")
    chat_type = message.get("chat_type", "")  # p2p / group
    message_type = message.get("message_type", "text")
    content_str = message.get("content", "{}")
    message_id = message.get("message_id", "")

    if not open_id:
        logger.warning("飞书消息事件缺少 open_id")
        return

    # 解析消息内容
    text = _parse_message_content(message_type, content_str)
    if not text:
        logger.info(f"收到飞书消息，但内容为空（type={message_type}）")
        return

    logger.info(f"飞书消息来自 {open_id}: {text[:50]}...")

    # 处理工单
    try:
        coordinator = get_coordinator()
        result = await coordinator.process(
            user_input=text,
            user_id=f"feishu_{open_id}",
            session_id=f"feishu_{open_id}",
        )

        # 构建回复
        category = result.get("category", "其他")
        response_text = result.get("response", "")
        ticket_id = result.get("ticket_id", "")
        elapsed = result.get("elapsed_seconds", 0)
        auto = result.get("auto_resolved", False)

        if auto:
            title = f"✅ 工单已自动处理"
            body = (
                f"**工单分类：** {category}\n"
                f"**工单编号：** `{ticket_id}`\n\n"
                f"---\n\n"
                f"{response_text}\n\n"
                f"---\n"
                f"⏱ 处理耗时 {elapsed} 秒"
            )
        else:
            title = f"🔄 工单已转人工"
            body = (
                f"**工单分类：** {category}\n"
                f"**工单编号：** `{ticket_id}`\n\n"
                f"---\n\n"
                f"{response_text}\n\n"
                f"---\n"
                f"⏱ 处理耗时 {elapsed} 秒"
            )

        # 发送卡片消息
        await send_card_message(
            open_id=open_id,
            title=title,
            body=body,
            note=f"回复工单 {ticket_id} · 企业工单智能 Agent",
        )

    except Exception as e:
        logger.error(f"工单处理异常: {e}", exc_info=True)
        await send_text_message(
            open_id=open_id,
            text=f"抱歉，系统处理您的请求时出现异常，请稍后重试。\n错误信息: {str(e)[:200]}",
        )


@router.get("/event")
async def verify_event(request: Request):
    """
    飞书事件订阅 URL 验证

    飞书会发送 GET 请求到回调地址进行验证
    """
    query_params = dict(request.query_params)

    challenge = query_params.get("challenge")
    token = query_params.get("token", "")

    config = get_config()
    if config.verification_token and token != config.verification_token:
        raise HTTPException(status_code=403, detail="Verification token mismatch")

    if challenge:
        return JSONResponse(content={"challenge": challenge})

    return {"status": "ok"}


@router.post("/event")
async def handle_event(request: Request):
    """
    飞书事件回调入口

    处理 im.message.receive_v1 等事件
    """
    body = await request.json()

    # URL 验证（飞书也会用 POST 方式验证）
    if body.get("type") == "url_verification":
        return JSONResponse(content={"challenge": body.get("challenge", "")})

    # 处理加密
    config = get_config()
    if config.encrypt_key and "encrypt" in body:
        decrypted = _decrypt(body["encrypt"], config.encrypt_key)
        if not decrypted:
            raise HTTPException(status_code=400, detail="Decrypt failed")
        body = json.loads(decrypted)

    # Token 验证
    token = body.get("token", "")
    if config.verification_token and token != config.verification_token:
        logger.warning("飞书事件 token 验证失败")
        return JSONResponse(content={"code": 0})  # 仍返回成功，避免飞书重试

    # 处理事件
    header = body.get("header", {})
    event_type = header.get("event_type", "")

    if event_type == "im.message.receive_v1":
        event = body.get("event", {})
        # 异步处理，避免飞书超时重试
        import asyncio
        asyncio.ensure_future(_handle_message_event(event))
    else:
        logger.debug(f"忽略飞书事件: {event_type}")

    return JSONResponse(content={"code": 0})


@router.post("/webhook")
async def webhook_bot(request: Request):
    """
    飞书群机器人 Webhook 模式

    当用户在群里 @机器人 时，飞书会推送消息到此地址。
    需要先在飞书群中添加自定义机器人，配置 Webhook 地址。
    """
    body = await request.json()

    # 解析消息
    text = ""
    if body.get("type") == "event" and body.get("event", {}).get("type") == "message":
        msg = body.get("event", {}).get("message", {})
        text = _parse_message_content(msg.get("msg_type", "text"), msg.get("content", "{}"))

    if not text:
        return JSONResponse(content={"msg": "ok"})

    # 处理工单
    try:
        coordinator = get_coordinator()
        result = await coordinator.process(
            user_input=text,
            user_id="feishu_webhook",
            session_id=f"webhook_{message_id_fallback(body)}",
        )
        logger.info(f"Webhook 工单处理完成: {result.get('ticket_id', '')}")
    except Exception as e:
        logger.error(f"Webhook 处理异常: {e}")

    return JSONResponse(content={"msg": "ok"})


def message_id_fallback(body: dict) -> str:
    """从 webhook 请求中提取消息 ID"""
    try:
        return body.get("event", {}).get("message", {}).get("message_id", "unknown")
    except Exception:
        return "unknown"
