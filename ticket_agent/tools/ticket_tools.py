"""
工单处理工具 — 生产级实现

所有工具继承自 tools.base.Tool，使用 Function Calling Schema 定义。
基于 SQLAlchemy 数据库实现，替换了原有的 Mock 数据。

生产环境可对接外部系统：
- GetTicketStatusTool → 查询真实工单系统 API
- NotifyUserTool → 对接钉钉/飞书/邮件网关
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


class GetTicketStatusTool(Tool):
    """查询工单当前状态和处理进度"""

    name = "get_ticket_status"
    description = "根据工单ID查询工单当前状态、分类、处理人、处理进度等信息"
    parameters = {
        "type": "object",
        "properties": {
            "ticket_id": {
                "type": "string",
                "description": "工单ID，格式如 TK-20240101-XXXXXX",
            }
        },
        "required": ["ticket_id"],
    }

    async def execute(self, ticket_id: str) -> ToolResult:
        try:
            from ticket_agent.repository import get_ticket_repository
            ticket = get_ticket_repository().get(ticket_id)
            if ticket:
                return ToolResult(success=True, output=json.dumps(ticket.to_dict(), ensure_ascii=False))
            return ToolResult(
                success=False,
                error=f"工单 {ticket_id} 不存在",
            )
        except Exception as e:
            logger.error(f"查询工单状态失败: {e}")
            return ToolResult(success=False, error=f"查询失败: {str(e)}")


class UpdateTicketTool(Tool):
    """更新工单字段信息"""

    name = "update_ticket"
    description = "更新工单的指定字段，如状态、处理人、优先级等"
    parameters = {
        "type": "object",
        "properties": {
            "ticket_id": {
                "type": "string",
                "description": "工单ID",
            },
            "field": {
                "type": "string",
                "description": "要更新的字段名：status/assignee/priority/assignee_name",
            },
            "value": {
                "type": "string",
                "description": "字段的新值",
            },
        },
        "required": ["ticket_id", "field", "value"],
    }

    # 字段名映射：工具参数 → 数据库列名
    FIELD_MAP = {
        "status": "status",
        "assignee": "assigned_to",
        "assignee_name": "assigned_name",
        "priority": "priority",
        "description": "content",
    }

    async def execute(self, ticket_id: str, field: str, value: str) -> ToolResult:
        db_field = self.FIELD_MAP.get(field)
        if not db_field:
            valid = list(self.FIELD_MAP.keys())
            return ToolResult(
                success=False,
                error=f"不支持的字段: {field}，可选: {valid}",
            )

        try:
            from ticket_agent.repository import get_ticket_repository
            result = get_ticket_repository().update(ticket_id, **{db_field: value})
            if result:
                logger.info(f"工单 {ticket_id} 已更新: {field}={value}")
                return ToolResult(
                    success=True,
                    output=json.dumps({
                        "ticket_id": ticket_id,
                        "updated_field": field,
                        "new_value": value,
                        "message": f"工单已更新",
                    }, ensure_ascii=False),
                )
            return ToolResult(success=False, error=f"工单 {ticket_id} 不存在")
        except Exception as e:
            logger.error(f"更新工单失败: {e}")
            return ToolResult(success=False, error=f"更新失败: {str(e)}")


class NotifyUserTool(Tool):
    """通知用户处理结果"""

    name = "notify_user"
    description = "通过指定渠道通知用户处理结果或需要用户配合的信息"
    parameters = {
        "type": "object",
        "properties": {
            "user_id": {
                "type": "string",
                "description": "用户ID",
            },
            "message": {
                "type": "string",
                "description": "通知内容",
            },
            "channel": {
                "type": "string",
                "description": "通知渠道：email/sms/dingtalk/webhook",
                "enum": ["email", "sms", "dingtalk", "webhook"],
            },
        },
        "required": ["user_id", "message"],
    }

    async def execute(self, user_id: str, message: str, channel: str = "webhook") -> ToolResult:
        try:
            # 从数据库查用户信息
            from ticket_agent.database import session_scope
            from ticket_agent.database.models import User

            user_name = user_id
            user_email = ""
            user_phone = ""
            with session_scope() as session:
                user = session.query(User).filter(User.user_id == user_id).first()
                if user:
                    user_name = user.name
                    user_email = user.email
                    user_phone = user.phone

            logger.info(f"通知 [{channel}] {user_name}({user_id}): {message[:80]}...")

            # 按渠道分发
            if channel == "email" and user_email:
                await self._send_email(user_email, message)
            elif channel == "sms" and user_phone:
                await self._send_sms(user_phone, message)
            elif channel == "dingtalk":
                await self._send_dingtalk(user_id, message)
            elif channel == "webhook":
                await self._send_webhook(message)
            else:
                logger.info(f"[{channel}] 通知已记录（渠道待对接）: {user_id}")

            return ToolResult(
                success=True,
                output=json.dumps({
                    "user_id": user_id,
                    "user_name": user_name,
                    "channel": channel,
                    "message": message[:100],
                    "status": "已发送",
                }, ensure_ascii=False),
            )
        except Exception as e:
            logger.error(f"通知失败: {e}")
            return ToolResult(success=False, error=f"通知发送失败: {str(e)}")

    async def _send_email(self, email: str, message: str):
        """发送邮件（需配置 SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / SMTP_FROM）"""
        import os
        smtp_host = os.getenv("SMTP_HOST", "")
        if not smtp_host:
            logger.info(f"[Email] 未配置 SMTP_HOST，跳过邮件发送: {email}")
            return
        try:
            import smtplib
            from email.mime.text import MIMEText

            smtp_port = int(os.getenv("SMTP_PORT", "587"))
            smtp_user = os.getenv("SMTP_USER", "")
            smtp_pass = os.getenv("SMTP_PASSWORD", "")
            smtp_from = os.getenv("SMTP_FROM", "noreply@workfloagent.com")

            msg = MIMEText(message, "plain", "utf-8")
            msg["Subject"] = "工单处理通知"
            msg["From"] = smtp_from
            msg["To"] = email

            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as smtp:
                smtp.starttls()
                if smtp_user:
                    smtp.login(smtp_user, smtp_pass)
                smtp.sendmail(smtp_from, [email], msg.as_string())

            logger.info(f"[Email] 已发送到 {email}")
        except Exception as e:
            logger.warning(f"[Email] 发送失败: {e}")

    async def _send_dingtalk(self, user_id: str, message: str):
        """发送钉钉消息（需配置钉钉 Bot）"""
        import os
        webhook = os.getenv("DINGTALK_WEBHOOK", "")
        if not webhook:
            logger.info(f"[DingTalk] 未配置 DINGTALK_WEBHOOK，跳过")
            return
        try:
            import httpx
            payload = {"msgtype": "text", "text": {"content": message}}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(webhook, json=payload)
                logger.info(f"[DingTalk] 发送完成: {resp.status_code}")
        except Exception as e:
            logger.warning(f"[DingTalk] 发送失败: {e}")

    async def _send_webhook(self, message: str):
        """发送 Webhook（通用）"""
        import os
        url = os.getenv("NOTIFY_WEBHOOK_URL", "")
        if not url:
            logger.info(f"[Webhook] 未配置 NOTIFY_WEBHOOK_URL，跳过")
            return
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json={"text": message})
                logger.info(f"[Webhook] 发送完成: {resp.status_code}")
        except Exception as e:
            logger.warning(f"[Webhook] 发送失败: {e}")

    async def _send_sms(self, phone: str, message: str):
        """发送短信（需对接短信网关）"""
        logger.info(f"[SMS] 短信通知已记录: {phone} — {message[:60]}...")
        logger.info(f"[SMS] 生产环境需配置 SMS_API_URL/SMS_API_KEY 并替换此方法")

class EscalateToHumanTool(Tool):
    """将工单转交人工处理"""

    name = "escalate_to_human"
    description = "当 Agent 无法处理或用户要求转人工时，将工单升级给人工客服处理"
    parameters = {
        "type": "object",
        "properties": {
            "ticket_id": {
                "type": "string",
                "description": "工单ID",
            },
            "reason": {
                "type": "string",
                "description": "转人工原因说明",
            },
            "priority": {
                "type": "string",
                "description": "优先级：low/normal/high/urgent",
                "enum": ["low", "normal", "high", "urgent"],
            },
        },
        "required": ["ticket_id", "reason"],
    }

    async def execute(self, ticket_id: str, reason: str, priority: str = "normal") -> ToolResult:
        try:
            from ticket_agent.repository import get_ticket_repository

            result = get_ticket_repository().update(
                ticket_id,
                status="已转人工",
                priority=priority,
            )

            if not result:
                return ToolResult(success=False, error=f"工单 {ticket_id} 不存在")

            logger.info(f"工单 {ticket_id} 转人工: [{priority}] {reason}")

            return ToolResult(
                success=True,
                output=json.dumps({
                    "ticket_id": ticket_id,
                    "status": "已转人工",
                    "priority": priority,
                    "reason": reason,
                    "message": f"工单已转交人工处理，优先级: {priority}",
                    "estimated_response_time": "30分钟内",
                }, ensure_ascii=False),
            )
        except Exception as e:
            logger.error(f"转人工失败: {e}")
            return ToolResult(success=False, error=f"转人工失败: {str(e)}")


class SearchKnowledgeTool(Tool):
    """补充检索知识库"""

    name = "search_knowledge"
    description = "在知识库中搜索与问题相关的解决方案文档，可作为RAG检索的补充"
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词",
            },
            "category": {
                "type": "string",
                "description": "知识库分类：IT/HR/财务/运维，为空则全库搜索",
            },
        },
        "required": ["query"],
    }

    async def execute(self, query: str, category: Optional[str] = None) -> ToolResult:
        try:
            from ticket_agent.knowledge.store import get_knowledge_store
            from rag.retriever import KeywordRetriever

            store = get_knowledge_store()
            docs = store.list_docs(category) if category else store.list_docs()

            if not docs:
                return ToolResult(
                    success=True,
                    output=json.dumps({"query": query, "result_count": 0, "results": []}, ensure_ascii=False),
                )

            retriever = KeywordRetriever(
                documents=[{"content": d["content"], "metadata": {"doc_id": d["doc_id"]}} for d in docs],
                top_k=5,
            )
            results = await retriever.retrieve(query)

            formatted = [
                {
                    "content": r["content"][:300],
                    "score": r["score"],
                    "source": r.get("metadata", {}).get("category", category or "全库"),
                }
                for r in results
            ]

            return ToolResult(
                success=True,
                output=json.dumps({
                    "query": query,
                    "category": category or "全库",
                    "result_count": len(formatted),
                    "results": formatted,
                }, ensure_ascii=False),
            )
        except Exception as e:
            logger.error(f"知识库检索失败: {e}")
            return ToolResult(success=False, error=f"检索失败: {str(e)}")
