"""
令牌桶限流器

用于 LLM API 调用和工具执行频率控制，防止超出 API Rate Limit（429 错误）。
线程安全，支持阻塞等待模式。

使用示例：
    bucket = TokenBucket(capacity=60, fill_rate=1.0)  # 每分钟 60 个令牌
    if bucket.consume(1):
        await call_api()
    else:
        logger.warning("API 调用被限流")

    # 阻塞等待模式（最多等 30 秒）
    if bucket.wait_and_consume(1, timeout=30.0):
        await call_api()
"""
import threading
import time
from typing import Optional


class TokenBucket:
    """
    令牌桶限流器

    :param capacity: 桶容量（最大突发量）
    :param fill_rate: 填充速率（每秒填充的令牌数）
    :param timeout: 默认等待超时（秒）
    """

    def __init__(self, capacity: int, fill_rate: float, timeout: float = 60.0):
        if capacity <= 0:
            raise ValueError("capacity 必须大于 0")
        if fill_rate <= 0:
            raise ValueError("fill_rate 必须大于 0")

        self.capacity = capacity
        self.fill_rate = fill_rate
        self.default_timeout = timeout

        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self):
        """补充令牌（线程安全，需在持锁时调用）"""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.fill_rate)
        self._last_refill = now

    def consume(self, tokens: int = 1) -> bool:
        """
        尝试消耗令牌

        :param tokens: 需要消耗的令牌数
        :return: 是否消耗成功
        """
        if tokens <= 0:
            return True

        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def wait_and_consume(self, tokens: int = 1, timeout: Optional[float] = None) -> bool:
        """
        阻塞直到有足够令牌或超时

        :param tokens: 需要消耗的令牌数
        :param timeout: 超时时间（秒），默认使用构造函数中的 timeout
        :return: 是否成功获取令牌
        """
        if tokens <= 0:
            return True

        deadline = time.monotonic() + (timeout if timeout is not None else self.default_timeout)

        while time.monotonic() < deadline:
            if self.consume(tokens):
                return True
            time.sleep(0.1)

        return False

    @property
    def available_tokens(self) -> float:
        """当前可用令牌数"""
        with self._lock:
            self._refill()
            return self._tokens

    def reset(self):
        """重置令牌桶为满"""
        with self._lock:
            self._tokens = float(self.capacity)
            self._last_refill = time.monotonic()


# ── 全局 LLM 限流器 ──

_llm_bucket: Optional[TokenBucket] = None
_llm_bucket_lock = threading.Lock()
_api_buckets: dict[str, TokenBucket] = {}
_api_buckets_lock = threading.Lock()


def get_llm_bucket(tpm: int = 60) -> TokenBucket:
    """
    获取全局 LLM 令牌桶（单例）

    :param tpm: 每分钟最大 Token 数（Tokens Per Minute）
    """
    global _llm_bucket
    if _llm_bucket is None:
        with _llm_bucket_lock:
            if _llm_bucket is None:
                _llm_bucket = TokenBucket(capacity=tpm, fill_rate=tpm / 60.0)
    return _llm_bucket


def consume_llm_token(tokens: int = 1, timeout: float = 30.0) -> bool:
    """
    消耗 LLM 调用令牌（便捷函数）

    :param tokens: 消耗的令牌数
    :param timeout: 等待超时
    :return: 是否成功
    """
    bucket = get_llm_bucket()
    return bucket.wait_and_consume(tokens, timeout=timeout)


def get_api_bucket(key: str, rpm: int = 60) -> TokenBucket:
    """
    获取 API 令牌桶（按 key 隔离，如 client_ip）

    :param key: 隔离键（如客户端 IP）
    :param rpm: 每分钟最大请求数
    """
    if key not in _api_buckets:
        with _api_buckets_lock:
            if key not in _api_buckets:
                _api_buckets[key] = TokenBucket(capacity=rpm, fill_rate=rpm / 60.0)
    return _api_buckets[key]
