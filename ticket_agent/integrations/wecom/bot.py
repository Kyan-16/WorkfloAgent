"""
企业微信机器人事件处理

处理企业微信回调：
- GET /api/wecom/callback: URL 验证（返回解密后的 echostr）
- POST /api/wecom/callback: 消息回调（XML 格式）
- POST /api/wecom/webhook: 群机器人 Webhook（快速测试）
"""
import hashlib
import json
import logging
import time
import xml.etree.ElementTree as ET
from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import PlainTextResponse, JSONResponse

from ticket_agent.integrations.wecom.config import get_config
from ticket_agent.integrations.wecom.client import send_text_message, send_card_message, send_webhook_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wecom", tags=["企业微信集成"])

_coordinator = None


def set_coordinator(coordinator):
    global _coordinator
    _coordinator = coordinator


def get_coordinator():
    if _coordinator is None:
        raise HTTPException(status_code=503, detail="Coordinator 未初始化")
    return _coordinator


# ─── 加解密 ───


def _sha1(*args: str) -> str:
    """SHA1 签名"""
    s = "".join(sorted(args))
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def _aes_decrypt(encoding_aes_key: str, encrypted: str) -> Optional[str]:
    """
    AES-256-CBC 解密（PKCS7 填充）

    企业微信文档：https://developer.work.weixin.qq.com/document/path/90968
    """
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        import base64

        # 1. 将 encoding_aes_key 做 base64 解码得到 AES Key
        aes_key = base64.b64decode(encoding_aes_key + "=")

        # 2. 将加密消息做 base64 解码
        encrypted_bytes = base64.b64decode(encrypted)

        # 3. 取前 16 字节为 IV
        iv = encrypted_bytes[:16]
        ciphertext = encrypted_bytes[16:]

        # 4. AES-256-CBC 解密
        cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv))
        decryptor = cipher.decryptor()
        decrypted = decryptor.update(ciphertext) + decryptor.finalize()

        # 5. 去除 PKCS7 填充
        pad_len = decrypted[-1]
        if pad_len < 1 or pad_len > 32:
            pad_len = 0
        content = decrypted[:-pad_len] if pad_len else decrypted

        # 6. 解析内容：前 4 字节为网络字节序的消息长度
        if len(content) < 16:
            return None
        msg_len_bytes = content[16:20]
        msg_len = int.from_bytes(msg_len_bytes, byteorder="big")
        msg = content[20:20 + msg_len]
        return msg.decode("utf-8")
    except Exception as e:
        logger.error(f"AES 解密失败: {e}")
        return None


def verify_signature(token: str, timestamp: str, nonce: str, echo_str: str, msg_signature: str) -> bool:
    """验证消息签名"""
    expected = _sha1(token, timestamp, nonce, echo_str)
    return expected == msg_signature


def parse_xml_message(xml_str: str) -> dict:
    """解析企业微信回调的 XML 消息"""
    try:
        root = ET.fromstring(xml_str)
        result = {}
        for child in root:
            result[child.tag] = child.text or ""
        return result
    except ET.ParseError as e:
        logger.error(f"XML 解析失败: {e}")
        return {}


def build_text_reply(to_user: str, from_user: str, content: str) -> str:
    """构建文本回复的 XML"""
    timestamp = str(int(time.time()))
    return f"""<xml>
<ToUserName><![CDATA[{to_user}]]></ToUserName>
<FromUserName><![CDATA[{from_user}]]></FromUserName>
<CreateTime>{timestamp}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{content}]]></Content>
</xml>"""


# ─── 路由 ───


@router.get("/callback")
async def verify_callback(request: Request):
    """
    企业微信回调 URL 验证

    企业微信会发 GET 请求验证 URL，需验证签名并解密 echostr。
    """
    params = dict(request.query_params)
    msg_signature = params.get("msg_signature", "")
    timestamp = params.get("timestamp", "")
    nonce = params.get("nonce", "")
    echostr = params.get("echostr", "")

    if not all([msg_signature, timestamp, nonce, echostr]):
        raise HTTPException(status_code=400, detail="缺少验证参数")

    config = get_config()

    # 验证签名
    if not verify_signature(config.token, timestamp, nonce, echostr, msg_signature):
        logger.warning("企业微信回调 URL 验证签名失败")
        raise HTTPException(status_code=403, detail="Signature mismatch")

    # 解密 echostr
    if config.encoding_aes_key:
        decrypted = _aes_decrypt(config.encoding_aes_key, echostr)
        if decrypted:
            return PlainTextResponse(decrypted)

    # 没有加密时直接返回 echostr
    return PlainTextResponse(echostr)


@router.post("/callback")
async def handle_callback(request: Request):
    """
    处理企业微信消息回调

    企业微信以 POST + XML 格式推送消息。
    解析消息 -> 调用 Coordinator 处理 -> 通过 API 回复。
    """
    params = dict(request.query_params)
    msg_signature = params.get("msg_signature", "")
    timestamp = params.get("timestamp", "")
    nonce = params.get("nonce", "")

    config = get_config()
    body = await request.body()
    xml_str = body.decode("utf-8")

    # 如果开启了加密，需要先解密
    if config.encoding_aes_key:
        parsed = parse_xml_message(xml_str)
        encrypted = parsed.get("Encrypt", "")
        if not encrypted:
            raise HTTPException(status_code=400, detail="缺少加密内容")
        if not verify_signature(config.token, timestamp, nonce, encrypted, msg_signature):
            logger.warning("企业微信消息签名验证失败")
            raise HTTPException(status_code=403, detail="Signature mismatch")
        decrypted = _aes_decrypt(config.encoding_aes_key, encrypted)
        if not decrypted:
            raise HTTPException(status_code=400, detail="解密失败")
        xml_str = decrypted

    # 解析消息
    msg = parse_xml_message(xml_str)
    from_user = msg.get("FromUserName", "")
    content = msg.get("Content", "")
    msg_type = msg.get("MsgType", "")

    logger.info(f"企业微信消息来自 {from_user}: {content[:50]}...")

    if msg_type == "text" and content and from_user:
        try:
            coordinator = get_coordinator()
            result = await coordinator.process(
                user_input=content,
                user_id=f"wecom_{from_user}",
                session_id=f"wecom_{from_user}",
            )

            response_text = result.get("response", "")
            ticket_id = result.get("ticket_id", "")
            elapsed = result.get("elapsed_seconds", 0)
            auto = result.get("auto_resolved", False)

            if auto:
                title = f"工单已自动处理 - {ticket_id}"
                desc = f"分类: {result.get('category', '')}\n\n{response_text[:300]}"
            else:
                title = f"工单已转人工 - {ticket_id}"
                desc = f"分类: {result.get('category', '')}\n\n{response_text[:300]}"

            await send_card_message(from_user, title, desc)

        except Exception as e:
            logger.error(f"工单处理异常: {e}", exc_info=True)
            await send_text_message(from_user, f"系统处理异常，请稍后重试。")

    # 返回空响应
    return PlainTextResponse("")


@router.post("/webhook")
async def webhook_bot(request: Request):
    """
    企业微信群机器人 Webhook

    在企业微信群里添加"群机器人" -> 选择 "Webhook 机器人"
    复制 Webhook URL，将 key 部分配到环境变量 WECOM_WEBHOOK_KEY
    """
    body = await request.json()

    # 解析文本消息
    content = ""
    if body.get("msgtype") == "text":
        content = body.get("text", {}).get("content", "").strip()

    if not content:
        return JSONResponse(content={"msg": "ok"})

    logger.info(f"企业微信群机器人消息: {content[:50]}...")

    # 处理工单
    try:
        coordinator = get_coordinator()
        result = await coordinator.process(
            user_input=content,
            user_id="wecom_webhook",
            session_id=f"webhook_{int(time.time())}",
        )

        response_text = result.get("response", "")
        ticket_id = result.get("ticket_id", "")

        # 通过 Webhook 回复群聊
        config = get_config()
        if config.webhook_key:
            reply = f"【工单处理结果】\n编号: {ticket_id}\n\n{response_text[:300]}"
            await send_webhook_message(config.webhook_key, reply)

        logger.info(f"企业微信群机器人工单处理完成: {ticket_id}")
    except Exception as e:
        logger.error(f"Webhook 处理异常: {e}")

    return JSONResponse(content={"msg": "ok"})
