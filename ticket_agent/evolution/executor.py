"""
自我进化 — 进化执行器

在满足触发条件时，在后台运行 Review Agent 审查会话内容，
决定是否需要更新核心记忆。支持并发控制、快照备份、审计日志。

工作流程：
  1. Trigger 判断是否需要进化
  2. Review Agent 审查对话内容
  3. 如果建议更新 → 创建快照 → 更新 MEMORY.md → 记录审计日志
  4. 如果失败 → 自动回滚到快照
"""
import asyncio
import logging
import threading
import time
from typing import Optional

from llm.base import LLMBase
from ticket_agent.memory.storage import MemoryStore
from ticket_agent.evolution.trigger import EvolutionTrigger
from ticket_agent.evolution.prompts import EvolutionPrompts

logger = logging.getLogger(__name__)

# 最大并发进化数
_MAX_CONCURRENT = 2


class EvolutionExecutor:
    """
    进化执行器。

    在满足触发条件时异步执行进化操作。
    线程安全，支持并发上限控制。

    使用示例：
        executor = EvolutionExecutor(llm=llm)
        result = await executor.try_evolve(
            topic="网络故障排除",
            content="用户反馈网络连接失败...",
            current_memory="- 检查 DNS 配置",
        )
    """

    _active_count = 0
    _lock = threading.Lock()

    def __init__(self, llm: LLMBase, store: Optional[MemoryStore] = None):
        self.llm = llm
        self.store = store or MemoryStore()
        self.trigger = EvolutionTrigger()

    @classmethod
    def _acquire_slot(cls) -> bool:
        """获取并发执行槽位"""
        with cls._lock:
            if cls._active_count >= _MAX_CONCURRENT:
                return False
            cls._active_count += 1
            return True

    @classmethod
    def _release_slot(cls):
        """释放并发执行槽位"""
        with cls._lock:
            cls._active_count = max(0, cls._active_count - 1)

    async def try_evolve(
        self,
        topic: str,
        content: str,
        current_memory: str = "",
        tool_rounds: int = 0,
        user_input: str = "",
        model_name: str = "",
        messages: list = None,
        force: bool = False,
    ) -> str:
        """
        尝试执行进化。

        Args:
            topic: 对话主题
            content: 对话内容
            current_memory: 当前的 MEMORY.md 内容
            tool_rounds: 工具调用轮次
            user_input: 用户输入
            model_name: 模型名称
            messages: 消息列表
            force: 是否强制触发

        Returns:
            操作结果描述，如 "[SILENT] 无需进化"、"[EVOLVED] 更新了 X 条记忆"
        """
        # 判断是否触发
        should_run, reason = self.trigger.should_evolve(
            messages=messages,
            tool_rounds=tool_rounds,
            user_input=user_input,
            model_name=model_name,
            force=force,
        )

        if not should_run:
            return "[SILENT] 无需进化"

        # 并发控制
        if not self._acquire_slot():
            return f"[SILENT] 并发上限 ({_MAX_CONCURRENT})"

        try:
            return await self._do_evolve(topic, content, current_memory)
        finally:
            self._release_slot()

    async def _do_evolve(self, topic: str, content: str, current_memory: str) -> str:
        """执行进化（已持有槽位）"""
        snapshot_id = None

        try:
            # 1. Review Agent 审查
            review = await EvolutionPrompts.parse_review_result(
                self.llm, topic, content, current_memory,
            )

            if review["action"] == "silent":
                return "[SILENT] 审查无变化"

            # 2. 创建快照
            snapshot_id = self.store.create_snapshot()

            # 3. 更新 MEMORY.md
            new_entries = review.get("new_entries", [])
            if new_entries:
                existing = current_memory.strip()
                new_content = "\n".join(new_entries)
                updated = f"{existing}\n{new_content}" if existing else new_content

                self.store.save_memory(updated)

                # 4. 记录审计日志
                self.store.log_evolution({
                    "action": "update_memory",
                    "reason": review.get("reason", ""),
                    "entries_count": len(new_entries),
                    "snapshot_id": snapshot_id,
                    "confidence": review.get("confidence", 0.0),
                })

                return f"[EVOLVED] 更新了 {len(new_entries)} 条记忆: {review.get('reason', '')[:100]}"

            return "[SILENT] 审查无新条目"

        except Exception as e:
            logger.error(f"进化过程出错: {e}", exc_info=True)

            # 失败时回滚
            if snapshot_id:
                try:
                    self.store.rollback(snapshot_id)
                    logger.info(f"已回滚到快照 {snapshot_id}")
                except Exception as rollback_err:
                    logger.error(f"回滚失败: {rollback_err}")

            # 记录失败日志
            self.store.log_evolution({
                "action": "error",
                "error": str(e),
                "topic": topic[:200],
            })

            return f"[ERROR] 进化失败: {str(e)}"

    async def try_evolve_later(self, delay_seconds: float = 5.0, **kwargs):
        """
        延迟执行进化（非阻塞）。

        启动一个后台任务，延迟指定时间后执行进化。
        适用于对话结束后延迟触发，避免阻塞主流程。
        """
        async def _delayed():
            await asyncio.sleep(delay_seconds)
            return await self.try_evolve(**kwargs)

        asyncio.create_task(_delayed())
