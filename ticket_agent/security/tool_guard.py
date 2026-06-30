"""
工具安全守卫

为 Agent 的工具调用提供安全控制：
- 权限分级
- 速率限制
- 操作审计
- 内容校验
"""
import logging
import json
import os
import time
from collections import defaultdict
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class ToolPermission(Enum):
    """工具权限等级"""
    AUTO = "auto"       # Agent 可自动调用
    CONFIRM = "confirm" # 需人工确认后执行
    BLOCKED = "blocked" # 禁止 AI 调用


# 工具权限表
TOOL_PERMISSIONS = {
    # 只读操作 — 安全
    "get_ticket_status": ToolPermission.AUTO,
    "search_knowledge": ToolPermission.AUTO,

    # 写入操作 — 需确认
    "update_ticket": ToolPermission.CONFIRM,
    "notify_user": ToolPermission.CONFIRM,
    "escalate_to_human": ToolPermission.CONFIRM,

    # 知识库操作 — 需确认
    # 新增的工具由 GuideGenerator 直接调用，不走 ReAct 循环
}


class ToolGuard:
    """
    工具安全守卫

    在 ReAct 循环中拦截工具调用，检查权限和频率。

    使用示例：
        guard = ToolGuard(session_id="sess_001")
        if guard.check("notify_user"):
            # 执行工具
            guard.record("notify_user", {"user_id": "xxx"})
    """

    def __init__(self, session_id: str = "default"):
        self.session_id = session_id
        # 速率限制：{tool_name: [timestamp, ...]}
        self._call_history: dict[str, list[float]] = defaultdict(list)
        # 审计日志：{tool_name: [entry, ...]}
        self._audit: list[dict] = []

        # 配置
        self.max_calls_per_minute = int(os.getenv("TOOL_MAX_CALLS_PER_MINUTE", "20"))
        self.limit_write_calls = int(os.getenv("TOOL_LIMIT_WRITE_CALLS", "5"))

    def check(self, tool_name: str) -> tuple[bool, str]:
        """
        检查工具是否允许调用

        Returns:
            (allowed: bool, reason: str)
        """
        # 1. 权限检查
        perm = TOOL_PERMISSIONS.get(tool_name, ToolPermission.AUTO)
        if perm == ToolPermission.BLOCKED:
            return False, f"工具 {tool_name} 已被禁止 AI 调用"
        if perm == ToolPermission.CONFIRM:
            return False, f"工具 {tool_name} 需人工确认，已记录待审批"

        # 2. 速率检查
        now = time.time()
        tool_history = self._call_history[tool_name]

        # 清理 1 分钟前的记录
        self._call_history[tool_name] = [t for t in tool_history if now - t < 60]

        # 总调用次数限制
        total_calls = sum(len(h) for h in self._call_history.values())
        if total_calls >= self.max_calls_per_minute:
            return False, f"每分钟工具调用上限 {self.max_calls_per_minute} 次，已超限"

        # 写入操作单独限制
        write_tools = {"update_ticket", "notify_user", "escalate_to_human"}
        if tool_name in write_tools:
            write_count = sum(
                1 for t in self._call_history.get(tool_name, [])
                if now - t < 60
            )
            if write_count >= self.limit_write_calls:
                return False, f"写入操作每分钟上限 {self.limit_write_calls} 次，已超限"

        return True, ""

    def record(self, tool_name: str, arguments: dict, result: str = ""):
        """记录工具调用"""
        now = time.time()
        self._call_history[tool_name].append(now)

        entry = {
            "timestamp": now,
            "tool": tool_name,
            "arguments": arguments,
            "result": result[:200],
            "session_id": self.session_id,
        }
        self._audit.append(entry)

        if tool_name in ("update_ticket", "notify_user", "escalate_to_human"):
            logger.info(f"[SECURITY] {tool_name} args={json.dumps(arguments, ensure_ascii=False)[:100]}")

    def get_audit_log(self) -> list[dict]:
        """获取当前会话的审计日志"""
        return list(self._audit)


class SecurityAudit:
    """
    安全审计

    记录所有涉及数据变更的操作，包括 AI 生成知识库文档。
    """

    def __init__(self):
        self._log: list[dict] = []

    def record(self, action: str, detail: dict):
        """记录安全事件"""
        entry = {
            "action": action,
            "detail": detail,
            "timestamp": time.time(),
        }
        self._log.append(entry)
        logger.info(f"[AUDIT] {action} {json.dumps(detail, ensure_ascii=False)[:100]}")

    def get_recent(self, limit: int = 50) -> list[dict]:
        return self._log[-limit:]


class ContentValidator:
    """
    AI 内容校验器

    Agent 生成的内容（包括操作指南）入库前进行安全检查。
    """

    @staticmethod
    def validate_guide(content: str) -> tuple[bool, str]:
        """
        校验 AI 生成的操作指南

        Returns:
            (valid: bool, reason: str)
        """
        if not content or len(content) < 20:
            return False, "内容太短"

        # 检查是否包含敏感关键词
        sensitive_keywords = ["删除数据库", "rm -rf", "DROP TABLE", "shutdown"]
        for kw in sensitive_keywords:
            if kw.lower() in content.lower():
                return False, f"内容包含敏感词汇: {kw}"

        # 检查基本结构
        required_sections = ["问题现象", "操作步骤"]
        missing = [s for s in required_sections if s not in content]
        if missing:
            logger.warning(f"指南缺少必要章节: {missing}")

        return True, ""

    @staticmethod
    def validate_ticket_update(field: str, value: str) -> tuple[bool, str]:
        """校验工单更新操作"""
        # 防止将工单状态改为冲突值
        valid_statuses = {"待处理", "处理中", "已解决", "已关闭", "已转人工"}
        if field == "status" and value not in valid_statuses:
            return False, f"无效的状态值: {value}"
        return True, ""


# 全局审计实例
_audit: Optional[SecurityAudit] = None


def get_audit() -> SecurityAudit:
    global _audit
    if _audit is None:
        _audit = SecurityAudit()
    return _audit
