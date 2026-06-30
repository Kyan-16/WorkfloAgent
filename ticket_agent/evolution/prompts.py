"""
自我进化 — Review Agent 提示词

Review Agent 是一个独立的 LLM 调用，用于判断会话内容是否需要进化，
以及如何进化（更新 MEMORY.md、修复技能、忽略等）。

提示词设计为保守风格：大多数情况下返回 [SILENT]。
"""
import logging
from typing import Optional

from llm.base import LLMBase, ChatMessage

logger = logging.getLogger(__name__)

# ── Review 提示词 ──

REVIEW_SYSTEM_PROMPT = """你是一个自我进化审查员（Review Agent）。你的任务是分析对话，判断是否需要更新系统的核心记忆。

规则：
1. 保守原则：只有发现明确的、可复用的知识时才更新。不确定就跳过。
2. 只记录事实：配置参数、故障解法、用户明确偏好、规范约定。
3. 不要记录：临时状态、一次性问题、显而易见的内容。
4. 每条记忆应该能指导未来的工单处理。

输出格式（严格 JSON）：
```json
{
    "action": "silent | update_memory",
    "reason": "判断依据的简短说明",
    "new_entries": ["以 - 开头的记忆条目，每条一行"],
    "confidence": 0.0-1.0
}
```

注意：
- action 为 "silent" 时，忽略其他字段
- action 为 "update_memory" 时，new_entries 至少包含一条
- confidence < 0.7 时建议返回 silent"""

REVIEW_USER_PROMPT = """请审查以下对话内容，判断是否需要更新核心记忆：

对话摘要：
{topic}

关键内容：
{content}

当前的记忆文件内容：
{current_memory}

请输出审查结果（JSON 格式）。"""


class EvolutionPrompts:
    """进化提示词管理器"""

    @staticmethod
    def build_review_messages(topic: str, content: str, current_memory: str) -> list:
        """构建审查消息"""
        return [
            ChatMessage(role="system", content=REVIEW_SYSTEM_PROMPT),
            ChatMessage(role="user", content=REVIEW_USER_PROMPT.format(
                topic=topic[:300],
                content=content[:6000],
                current_memory=current_memory[:2000] or "（空）",
            )),
        ]

    @staticmethod
    async def parse_review_result(llm: LLMBase, topic: str, content: str,
                                    current_memory: str) -> dict:
        """
        执行审查并解析结果。

        Returns:
            {"action": "silent" | "update_memory", "reason": str,
             "new_entries": list[str], "confidence": float}
        """
        from utils.json_parser import parse_json

        messages = EvolutionPrompts.build_review_messages(topic, content, current_memory)
        response = await llm.generate(messages=messages, temperature=0.1, max_tokens=1024)

        if response.finish_reason == "error":
            logger.warning(f"Review Agent 调用失败: {response.content}")
            return {"action": "silent", "reason": "LLM 调用失败"}

        result = parse_json(response.content)

        if not result.success:
            logger.warning("Review Agent 返回非 JSON 格式")
            return {"action": "silent", "reason": "解析失败"}

        value = result.value
        action = value.get("action", "silent")
        confidence = value.get("confidence", 0.0)

        # 低置信度 → silent
        if confidence < 0.7 and action != "silent":
            logger.info(f"Review Agent 置信度不足 ({confidence}), 跳过")
            return {"action": "silent", "reason": f"置信度不足 ({confidence})"}

        return {
            "action": action,
            "reason": value.get("reason", ""),
            "new_entries": value.get("new_entries", []),
            "confidence": confidence,
        }
