"""
Embedding 抽象层

支持多种 Embedding 模型：
- DashScope text-embedding-v2
- OpenAI text-embedding-ada-002 / text-embedding-3-small

所有 Embedding 方法均为 async，同步 SDK 调用通过 asyncio.to_thread 异步化。
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class EmbeddingBase(ABC):
    """Embedding 基类（所有方法均为 async）"""

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        """单条文本向量化"""
        ...

    @abstractmethod
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量文本向量化"""
        ...


class DashScopeEmbedding(EmbeddingBase):
    """
    DashScope Embedding 实现

    使用阿里云 text-embedding-v2 模型，向量维度 1536。
    """

    def __init__(self, model: str = "text-embedding-v2", api_key: str = ""):
        self.model = model
        self.api_key = api_key

    async def embed_query(self, text: str) -> list[float]:
        """单条文本向量化（在线程池执行）"""
        text = (text or "").strip()
        if not text:
            return []

        if len(text) > 2048:
            text = text[:2048]

        try:
            import dashscope
            from dashscope import TextEmbedding

            def _do_embed():
                dashscope.api_key = self.api_key
                response = TextEmbedding.call(model=self.model, input=text)
                if response.status_code == 200:
                    return response.output["embeddings"][0]["embedding"]
                else:
                    raise RuntimeError(getattr(response, "message", str(response)))

            return await asyncio.to_thread(_do_embed)
        except ImportError:
            logger.error("dashscope 未安装")
            raise
        except Exception as e:
            logger.error(f"Embedding 异常: {e}")
            raise

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量文本向量化（在线程池执行）"""
        valid_texts = [t.strip()[:4096] for t in texts if t and t.strip()]
        if not valid_texts:
            return []

        try:
            import dashscope
            from dashscope import TextEmbedding

            def _do_embed():
                dashscope.api_key = self.api_key
                response = TextEmbedding.call(model=self.model, input=valid_texts)
                if response.status_code == 200:
                    return [item["embedding"] for item in response.output["embeddings"]]
                else:
                    raise RuntimeError(getattr(response, "message", str(response)))

            return await asyncio.to_thread(_do_embed)
        except Exception as e:
            logger.error(f"批量 Embedding 异常: {e}")
            raise


class OpenAIEmbedding(EmbeddingBase):
    """
    OpenAI Embedding 实现

    支持 text-embedding-3-small / text-embedding-ada-002 等模型。
    也兼容其他支持 OpenAI Embedding API 的服务。
    """

    def __init__(self, model: str = "text-embedding-3-small", api_key: str = "", base_url: Optional[str] = None):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url

    def _get_client(self):
        from openai import OpenAI
        kwargs = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return OpenAI(**kwargs)

    async def embed_query(self, text: str) -> list[float]:
        """单条文本向量化（在线程池执行）"""
        try:
            def _do_embed():
                client = self._get_client()
                response = client.embeddings.create(model=self.model, input=text)
                return response.data[0].embedding

            return await asyncio.to_thread(_do_embed)
        except Exception as e:
            logger.error(f"OpenAI Embedding 异常: {e}")
            raise

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """批量文本向量化（在线程池执行）"""
        try:
            def _do_embed():
                client = self._get_client()
                response = client.embeddings.create(model=self.model, input=texts)
                return [item.embedding for item in response.data]

            return await asyncio.to_thread(_do_embed)
        except Exception as e:
            logger.error(f"OpenAI 批量 Embedding 异常: {e}")
            raise


def create_embedding(
    provider: str = "dashscope",
    model: str = "",
    api_key: str = "",
    base_url: Optional[str] = None,
) -> EmbeddingBase:
    """
    创建 Embedding 实例（工厂函数）

    使用示例：
        embedding = create_embedding(provider="dashscope", api_key="sk-xxx")
        vector = await embedding.embed_query("你好")
    """
    provider = (provider or "dashscope").lower()
    if provider == "dashscope":
        return DashScopeEmbedding(model=model or "text-embedding-v2", api_key=api_key)
    if provider == "openai":
        return OpenAIEmbedding(
            model=model or "text-embedding-3-small",
            api_key=api_key,
            base_url=base_url,
        )
    raise ValueError(f"不支持的 Embedding Provider: {provider}")
