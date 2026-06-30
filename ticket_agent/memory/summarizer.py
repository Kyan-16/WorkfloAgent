"""
三层记忆 — 每日总结 + Deep Dream 蒸馏

功能：
1. generate_daily_summary(): 会话结束后生成每日总结
2. deep_dream(): 对核心记忆进行 Deep Dream 蒸馏

提示词设计为保守风格：不确定时留空，确保不引入错误信息。
"""
import logging
from datetime import date
from typing import Optional

from llm.base import LLMBase, ChatMessage, LLMResponse
from ticket_agent.memory.storage import MemoryStore

logger = logging.getLogger(__name__)

# ── 每日总结提示词 ──

DAILY_SUMMARIZE_SYSTEM = """你是一个专业的对话分析师。你的任务是从对话中提取有价值的信息，生成简洁的总结。

要求：
1. 只提取对未来有帮助的信息
2. 不确定的内容不要编造
3. 保持客观，不要添加主观评价
4. 如果对话中没有值得记录的信息，返回空字符串

输出格式（Markdown）：
- 技术细节：涉及的具体技术方案、配置、命令等
- 决策记录：明确做出的决策及其理由
- 用户偏好：用户的表达习惯、偏好设置等
- 待办事项：明确提到的后续任务"""

DAILY_SUMMARIZE_USER = """请分析以下对话，生成每日总结：

对话摘要：
{topic}

关键内容：
{content}

请只输出总结内容，如果没有值得记录的信息，输出空字符串。"""

# ── Deep Dream 提示词 ──

DEEP_DREAM_SYSTEM = """你是一个核心记忆精炼专家。你的任务是将现有的核心记忆与新的每日总结整合，输出更精炼、更有价值的核心记忆。

规则：
1. 去重：合并重复或相似的内容
2. 优先级：保留高频出现的模式和有具体操作指导的内容
3. 裁剪：只保留对未来有实际价值的信息
4. 格式：每条以 - 开头，一行一条
5. 上限：最多 50 条
6. 语言：保持与输入相同的语言

只输出精炼后的记忆列表，不要其他解释。"""

DEEP_DREAM_USER = """现有核心记忆：
{core_memory}

今日新增内容（最近 {days} 天）：
{daily_entries}

请整合并输出精炼后的核心记忆（最多 50 条）。"""


async def generate_daily_summary(llm: LLMBase, topic: str, content: str) -> str:
    """
    生成每日总结。

    调用 LLM 分析对话内容，提取有价值的信息。
    如果对话中没有值得记录的内容，返回空字符串。

    Args:
        llm: LLM 实例
        topic: 对话主题（简短描述）
        content: 对话内容

    Returns:
        生成的总结文本，或空字符串
    """
    messages = [
        ChatMessage(role="system", content=DAILY_SUMMARIZE_SYSTEM),
        ChatMessage(role="user", content=DAILY_SUMMARIZE_USER.format(
            topic=topic[:200],
            content=content[:4000],
        )),
    ]

    response = await llm.generate(messages=messages, temperature=0.3, max_tokens=1024)

    if response.finish_reason == "error":
        logger.warning(f"每日总结生成失败: {response.content}")
        return ""

    result = response.content.strip()
    return result if result and result != "空" and result != "无" else ""


async def deep_dream(llm: LLMBase, store: MemoryStore, days: int = 7) -> str:
    """
    核心记忆 Deep Dream 蒸馏。

    读取现有 MEMORY.md 和最近 N 天的 daily 总结，
    调用 LLM 整合去重，写回 MEMORY.md。

    Args:
        llm: LLM 实例
        store: MemoryStore 实例
        days: 读取最近多少天的 daily 总结

    Returns:
        蒸馏后的核心记忆内容
    """
    core_memory = store.load_memory()
    daily_entries = store.load_daily(days=days)

    if not core_memory and not daily_entries:
        logger.info("Deep Dream 跳过：无记忆数据")
        return ""

    # 格式化 daily 总结
    daily_text = ""
    for entry in daily_entries:
        daily_text += f"\n### {entry['date']}\n{entry['content'][:2000]}\n"

    if not daily_text:
        logger.info("Deep Dream 跳过：无新的 daily 数据")
        return core_memory

    messages = [
        ChatMessage(role="system", content=DEEP_DREAM_SYSTEM),
        ChatMessage(role="user", content=DEEP_DREAM_USER.format(
            core_memory=core_memory[:3000] if core_memory else "（无）",
            daily_entries=daily_text[:5000],
            days=days,
        )),
    ]

    response = await llm.generate(messages=messages, temperature=0.3, max_tokens=2048)

    if response.finish_reason == "error":
        logger.error(f"Deep Dream 失败: {response.content}")
        return core_memory

    result = response.content.strip()
    if result:
        store.save_memory(result)
        logger.info(f"Deep Dream 完成，输出 {len(result)} 字符")
    else:
        logger.warning("Deep Dream 输出为空，保留原有记忆")

    return result or core_memory
