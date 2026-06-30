"""
工具熔断器 — 有限循环检测 + 自动熔断

追踪每个工具按参数 hash 的调用和失败记录，
在检测到有限循环或连续失败时自动熔断。

熔断规则：
- 同一参数连续失败 3 次 → 阻塞该参数组合
- 同一参数成功 5 次 → 阻塞（工具成功但 LLM 循环调用）
- 任意参数总失败 6 次 → 停止新工具调用
- 任意参数总失败 8 次 → 致命熔断，返回用户道歉
"""
import hashlib
import json
import logging
import threading
from collections import defaultdict

logger = logging.getLogger(__name__)


class ToolCircuitBreaker:
    """
    工具熔断器（线程安全）

    使用示例：
        breaker = ToolCircuitBreaker()

        # 在执行前检查
        ok, msg = breaker.check_call("web_search", '{"query": "weather"}')
        if not ok:
            return ToolResult(success=False, error=msg)

        # 执行后记录结果
        breaker.record_success("web_search", '{"query": "weather"}')
        # 或
        breaker.record_failure("web_search", '{"query": "weather"}')
    """

    # 熔断阈值
    CONS_FAILURES_BLOCK = 3    # 同一参数连续失败
    SUCCESS_LOOP_BLOCK = 5     # 同一参数成功次数
    TOTAL_FAILURES_SOFT = 6    # 总失败次数（软停止）
    TOTAL_FAILURES_HARD = 8    # 总失败次数（致命熔断）

    def __init__(self):
        self._lock = threading.Lock()
        self._failures_by_key: dict[str, int] = defaultdict(int)
        self._calls_by_key: dict[str, int] = defaultdict(int)
        self._consecutive_failures_by_key: dict[str, int] = defaultdict(int)
        self._blocked_keys: set[str] = set()
        self._total_failures = 0
        self._total_calls = 0

    def _make_key(self, func_name: str, args: str) -> str:
        """生成参数 hash key"""
        key = f"{func_name}:{args}"
        return hashlib.md5(key.encode("utf-8")).hexdigest()

    def check_call(self, func_name: str, args: str) -> tuple[bool, str]:
        """
        检查是否允许执行工具调用。

        Returns:
            (是否允许, 不允许的原因)
        """
        key = self._make_key(func_name, args)

        with self._lock:
            # 致命熔断
            if self._total_failures >= self.TOTAL_FAILURES_HARD:
                return (
                    False,
                    "非常抱歉，系统检测到工具调用异常，已自动停止以防止进一步错误。请重新描述您的问题。",
                )

            # 参数级阻塞
            if key in self._blocked_keys:
                return (
                    False,
                    f"工具 '{func_name}' 的相同调用已被阻止（可能陷入循环），请调整参数后重试。",
                )

            # 软停止
            if self._total_failures >= self.TOTAL_FAILURES_SOFT:
                return (
                    False,
                    f"工具调用失败次数过多 ({self._total_failures} 次)，请重新描述您的问题。",
                )

            return True, ""

    def record_success(self, func_name: str, args: str):
        """记录成功的工具调用"""
        key = self._make_key(func_name, args)
        with self._lock:
            self._calls_by_key[key] += 1
            self._consecutive_failures_by_key[key] = 0
            self._total_calls += 1

            # 循环检测：同一参数成功太多次
            if self._calls_by_key[key] >= self.SUCCESS_LOOP_BLOCK:
                self._blocked_keys.add(key)
                logger.warning(
                    f"工具 '{func_name}' 同一参数成功 {self._calls_by_key[key]} 次，"
                    f"已自动阻塞（可能陷入循环）"
                )

    def record_failure(self, func_name: str, args: str):
        """记录失败的工具调用"""
        key = self._make_key(func_name, args)
        with self._lock:
            self._failures_by_key[key] += 1
            self._consecutive_failures_by_key[key] += 1
            self._total_failures += 1
            self._total_calls += 1

            # 连续失败 → 阻塞该参数
            if self._consecutive_failures_by_key[key] >= self.CONS_FAILURES_BLOCK:
                self._blocked_keys.add(key)
                logger.warning(
                    f"工具 '{func_name}' 连续失败 "
                    f"{self._consecutive_failures_by_key[key]} 次，已自动阻塞"
                )

            # 日志：总失败次数
            if self._total_failures in (self.TOTAL_FAILURES_SOFT, self.TOTAL_FAILURES_HARD):
                logger.error(
                    f"工具熔断器: 总失败次数达到 {self._total_failures}，"
                    f"{'致命熔断' if self._total_failures >= self.TOTAL_FAILURES_HARD else '软停止'}"
                )

    @property
    def stats(self) -> dict:
        """获取熔断器统计信息"""
        with self._lock:
            return {
                "total_calls": self._total_calls,
                "total_failures": self._total_failures,
                "blocked_keys": len(self._blocked_keys),
                "is_hard_breaked": self._total_failures >= self.TOTAL_FAILURES_HARD,
                "is_soft_stopped": self._total_failures >= self.TOTAL_FAILURES_SOFT,
            }

    def reset(self):
        """重置熔断器状态"""
        with self._lock:
            self._failures_by_key.clear()
            self._calls_by_key.clear()
            self._consecutive_failures_by_key.clear()
            self._blocked_keys.clear()
            self._total_failures = 0
            self._total_calls = 0
