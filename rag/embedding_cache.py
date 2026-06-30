"""
Embedding 结果缓存

避免同一段文本在短时间内重复调用 Embedding API。
使用 LRU 策略，按 provider+model 分命名空间缓存。
"""
import hashlib
import logging
import time
from collections import OrderedDict
from typing import Optional

logger = logging.getLogger(__name__)


class EmbeddingCache:
    """
    轻量级 Embedding 缓存 (LRU)

    使用示例：
        cache = EmbeddingCache(max_size=1000, ttl=300)
        key = cache.make_key("text-embedding-v3", text)
        if cache.has(key):
            vector = cache.get(key)
        else:
            vector = embed(text)
            cache.set(key, vector)
    """

    def __init__(self, max_size: int = 1000, ttl: int = 300):
        """
        :param max_size: 最大缓存条数
        :param ttl: 缓存有效期（秒），默认 5 分钟
        """
        self.max_size = max_size
        self.ttl = ttl
        self._cache: OrderedDict[str, tuple[list[float], float]] = OrderedDict()

    @staticmethod
    def make_key(provider: str, model: str, text: str) -> str:
        """生成缓存键"""
        raw = f"{provider}::{model}::{text.strip()}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def has(self, key: str) -> bool:
        if key not in self._cache:
            return False
        _, ts = self._cache[key]
        if time.time() - ts > self.ttl:
            del self._cache[key]
            return False
        return True

    def get(self, key: str) -> Optional[list[float]]:
        if not self.has(key):
            return None
        self._cache.move_to_end(key)
        return self._cache[key][0]

    def set(self, key: str, vector: list[float]):
        while len(self._cache) >= self.max_size:
            self._cache.popitem(last=False)
        self._cache[key] = (vector, time.time())

    def clear(self):
        self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)


# 全局单例
_global_cache: Optional[EmbeddingCache] = None


def get_embedding_cache() -> EmbeddingCache:
    global _global_cache
    if _global_cache is None:
        _global_cache = EmbeddingCache()
    return _global_cache
