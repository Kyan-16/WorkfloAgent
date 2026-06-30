"""
自我进化 — 触发条件判断

决定是否需要对当前会话执行进化操作。
触发条件组合使用，满足任一即可触发。
"""
import logging
from typing import Optional

from llm.token_estimator import should_trim

logger = logging.getLogger(__name__)


class EvolutionTrigger:
    """
    进化触发条件判断器

    触发条件：
    1. Token 使用率超过上下文窗口的 80%
    2. 连续工具调用轮次过多（≥5）
    3. 用户明确要求"记住"或"优化"
    4. 距离上次进化超过指定时间
    5. 系统启动后的首次触发机会
    """

    # 用户意图关键词（触发进化）
    REMEMBER_KEYWORDS = [
        "记住", "记得", "保存", "记录",
        "记住这个", "下次注意", "以后记得",
        "优化", "改进", "改善",
        "learn", "remember", "save",
    ]

    # 工具调用轮次阈值
    MAX_TOOL_ROUNDS = 5

    def __init__(
        self,
        min_interval_minutes: int = 30,
        tool_round_threshold: int = 5,
        token_threshold: float = 0.8,
    ):
        self.min_interval_minutes = min_interval_minutes
        self.tool_round_threshold = tool_round_threshold
        self.token_threshold = token_threshold
        self._last_trigger_time: Optional[float] = None

    def should_evolve(
        self,
        messages: list = None,
        tool_rounds: int = 0,
        user_input: str = "",
        model_name: str = "",
        force: bool = False,
    ) -> tuple[bool, str]:
        """
        判断是否需要进化。

        Args:
            messages: 消息列表（用于 token 估算）
            tool_rounds: 当前会话的工具调用轮次
            user_input: 最近的用户输入
            model_name: 模型名称
            force: 是否强制触发

        Returns:
            (是否触发, 触发原因)
        """
        import time

        if force:
            self._last_trigger_time = time.time()
            return True, "强制触发"

        # 条件 1: Token 使用率过高
        if messages and should_trim(messages, model_name, self.token_threshold):
            self._last_trigger_time = time.time()
            return True, f"Token 使用率超过 {self.token_threshold*100:.0f}%"

        # 条件 2: 工具调用轮次过多
        if tool_rounds >= self.tool_round_threshold:
            self._last_trigger_time = time.time()
            return True, f"工具调用轮次 ({tool_rounds}) 超过阈值 ({self.tool_round_threshold})"

        # 条件 3: 用户要求记住
        if user_input:
            for keyword in self.REMEMBER_KEYWORDS:
                if keyword in user_input.lower():
                    self._last_trigger_time = time.time()
                    return True, f"用户意图触发（关键词: {keyword}）"

        # 条件 4: 间隔时间已到
        if self._last_trigger_time is not None:
            elapsed = (time.time() - self._last_trigger_time) / 60
            if elapsed >= self.min_interval_minutes:
                self._last_trigger_time = time.time()
                return True, f"距上次进化已超过 {self.min_interval_minutes} 分钟"

        return False, ""

    def get_time_since_last(self) -> Optional[float]:
        """获取距上次触发的时间（分钟）"""
        import time
        if self._last_trigger_time is None:
            return None
        return (time.time() - self._last_trigger_time) / 60

    def reset(self):
        """重置触发状态"""
        self._last_trigger_time = None


# 全局单例
_global_trigger: Optional[EvolutionTrigger] = None


def get_trigger() -> EvolutionTrigger:
    """获取全局进化的触发器实例"""
    global _global_trigger
    if _global_trigger is None:
        _global_trigger = EvolutionTrigger()
    return _global_trigger
