"""
三层记忆管理器

统一管理三层记忆：
1. Context 层：当前会话消息（保持与原有 MemoryBase 兼容）
2. Daily 层：跨会话的每日总结
3. Core 层：Deep Dream 蒸馏后的核心记忆

使用方法：
    manager = MemoryManager(llm=llm, base_dir="data/memory")

    # 每次对话结束后调用
    await manager.on_conversation_end(session_id, messages, topic)

    # 每次对话前调用，获取注入 system prompt 的记忆上下文
    context = await manager.get_memory_context()
    system_prompt += context
"""
import logging
from typing import Optional

from llm.base import LLMBase
from ticket_agent.memory.storage import MemoryStore
from ticket_agent.memory.conversation_store import ConversationStore
from ticket_agent.memory.summarizer import generate_daily_summary, deep_dream

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    三层记忆管理器

    组合 MemoryStore（文件存储）+ ConversationStore（SQLite 存储）+ Summarizer，
    提供统一的高层接口。

    :param llm: LLM 实例（用于总结和蒸馏）
    :param base_dir: 记忆文件存储目录
    :param db_path: SQLite 数据库路径
    :param deep_dream_interval_minutes: Deep Dream 最小间隔（分钟）
    """

    def __init__(
        self,
        llm: LLMBase,
        base_dir: str = "data/memory",
        db_path: str = "data/ticket_agent.db",
        deep_dream_interval_minutes: int = 60,
    ):
        self.llm = llm
        self.store = MemoryStore(base_dir)
        self.conversation_store = ConversationStore(db_path)
        self.deep_dream_interval_minutes = deep_dream_interval_minutes
        self._last_deep_dream_time: Optional[float] = None

    # ── 对话生命周期 ──

    async def on_conversation_start(self, session_id: str):
        """
        对话开始时调用。

        在 SQLite 中创建/更新会话记录。
        """
        self.conversation_store.create_session(session_id)

    async def on_conversation_end(self, session_id: str, messages: list,
                                   topic: str = ""):
        """
        对话结束时调用。

        流程：
        1. 更新会话活动时间
        2. 生成 Daily 总结并保存
        3. 检查是否需要 Deep Dream

        Args:
            session_id: 会话 ID
            messages: 对话消息列表
            topic: 对话主题（简短描述）
        """
        # 1. 更新会话活动
        self.conversation_store.update_session_activity(session_id)
        self.conversation_store.add_message(
            session_id, "system", f"对话完成: {topic}",
            metadata={"event": "conversation_end"},
        )

        # 2. 检查是否需要生成 Daily 总结
        if len(messages) < 2:
            return  # 太短的对话不总结

        try:
            # 提取对话内容用于总结
            content_parts = []
            for m in messages[-20:]:  # 只取最后 20 条
                role = getattr(m, "role", m.get("role", "unknown"))
                text = getattr(m, "content", m.get("content", ""))
                if isinstance(text, str) and text.strip():
                    content_parts.append(f"{role}: {text[:500]}")

            full_content = "\n".join(content_parts)
            summary = await generate_daily_summary(self.llm, topic, full_content)

            if summary:
                self.store.save_daily(summary)
                logger.info(f"Daily 总结已生成 (session={session_id})")
        except Exception as e:
            logger.warning(f"Daily 总结生成失败: {e}")

        # 3. 检查是否需要 Deep Dream
        await self._maybe_deep_dream()

    async def get_memory_context(self) -> str:
        """
        获取记忆上下文（注入到 system prompt 中）。

        返回格式化的记忆上下文文本。

        Returns:
            记忆上下文文本，或空字符串
        """
        parts = []

        # Core 层
        core = self.store.load_memory()
        if core:
            parts.append(f"【核心记忆】\n{core}\n")

        # Daily 层（最近 3 天摘要）
        dailies = self.store.load_daily(days=3)
        if dailies:
            daily_text = "\n".join(
                f"[{e['date']}] {e['content'][:300]}"
                for e in dailies if e.get("content")
            )
            if daily_text:
                parts.append(f"【近期对话总结】\n{daily_text}\n")

        return "\n".join(parts)

    async def _maybe_deep_dream(self):
        """检查并执行 Deep Dream（有时间间隔控制）"""
        import time

        now = time.time()
        if self._last_deep_dream_time is not None:
            elapsed = (now - self._last_deep_dream_time) / 60
            if elapsed < self.deep_dream_interval_minutes:
                return  # 未到间隔时间

        self._last_deep_dream_time = now

        try:
            result = await deep_dream(self.llm, self.store, days=7)
            if result:
                self.store.log_evolution({
                    "action": "deep_dream",
                    "memory_length": len(result),
                })
                logger.info("Deep Dream 完成")
        except Exception as e:
            logger.warning(f"Deep Dream 执行失败: {e}")

    def get_conversation_history(self, session_id: str, limit: int = 50) -> list[dict]:
        """获取会话历史（从 SQLite 读取）"""
        return self.conversation_store.get_messages(session_id, limit=limit)

    def force_deep_dream(self) -> str:
        """强制触发 Deep Dream（手动调用）"""
        import asyncio
        return asyncio.run(deep_dream(self.llm, self.store, days=30))
