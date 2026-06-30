"""
Cross-encoder 精排器

在粗召（向量/关键词）结果之上，使用 Cross-encoder 模型做第二遍精排。
相比双塔 Embedding，Cross-encoder 精度更高，但速度较慢——适合对 Top-20 精排到 Top-5。

支持两种模式：
1. API 模式：通过 LLM API 模拟 Cross-encoder 打分（无需额外模型）
2. 本地模型模式：使用 sentence-transformers cross-encoder 模型
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    """
    Cross-encoder 精排器

    对检索结果重新打分排序，显著提升 Top-K 准确率。

    使用示例：
        reranker = CrossEncoderReranker(mode="llm", llm=llm)
        docs = await retriever.retrieve("电脑蓝屏", top_k=20)
        reranked = await reranker.rerank("电脑蓝屏", docs, top_k=5)
    """

    def __init__(
        self,
        mode: str = "llm",
        model_name: str = "",
        llm=None,
        batch_size: int = 10,
    ):
        """
        :param mode: "llm" 用 LLM 打分 | "local" 用本地 cross-encoder 模型
        :param model_name: 本地模型名（mode="local" 时生效），如 "BAAI/bge-reranker-v2-m3"
        :param llm: LLM 实例（mode="llm" 时生效）
        :param batch_size: 批处理大小
        """
        self.mode = mode
        self.model_name = model_name
        self.llm = llm
        self.batch_size = batch_size
        self._model = None

    def _get_local_model(self):
        """懒加载本地模型"""
        if self._model is not None:
            return self._model
        try:
            from sentence_transformers import CrossEncoder
            model_name = self.model_name or "BAAI/bge-reranker-v2-m3"
            self._model = CrossEncoder(model_name)
            logger.info(f"Cross-encoder 模型已加载: {model_name}")
            return self._model
        except ImportError:
            logger.warning("sentence-transformers 未安装，回退到 LLM 模式")
            self.mode = "llm"
            return None

    async def rerank(
        self,
        query: str,
        docs: list[dict],
        top_k: Optional[int] = None,
    ) -> list[dict]:
        """
        对文档列表进行精排

        :param query: 原始查询
        :param docs: 粗召结果列表
        :param top_k: 返回数量，默认全部
        :returns: 按新分数降序的文档列表（每个文档会增加 cross_encoder_score 字段）
        """
        if not docs:
            return []

        if self.mode == "local":
            return await self._rerank_local(query, docs, top_k)
        else:
            return await self._rerank_llm(query, docs, top_k)

    async def _rerank_local(self, query: str, docs: list[dict], top_k: Optional[int] = None) -> list[dict]:
        """使用本地 Cross-encoder 模型精排"""
        model = self._get_local_model()
        if model is None:
            return self._rerank_fallback(docs, top_k)

        pairs = [(query, d.get("content", "")) for d in docs]
        try:
            scores = model.predict(pairs, batch_size=self.batch_size)
            for doc, score in zip(docs, scores):
                score_val = float(score)
                doc["cross_encoder_score"] = round(score_val, 4)
            docs.sort(key=lambda x: x.get("cross_encoder_score", 0), reverse=True)
            k = top_k or len(docs)
            logger.info(f"Cross-encoder 精排完成: {len(docs)} 篇 → Top-{k}")
            return docs[:k]
        except Exception as e:
            logger.warning(f"Cross-encoder 预测失败: {e}，使用原始分排序")
            return self._rerank_fallback(docs, top_k)

    async def _rerank_llm(self, query: str, docs: list[dict], top_k: Optional[int] = None) -> list[dict]:
        """使用 LLM 对文档相关性打分"""
        if not self.llm:
            logger.warning("Cross-encoder LLM 模式需要传入 llm 实例，使用原始分排序")
            return self._rerank_fallback(docs, top_k)

        from llm.base import ChatMessage

        scored = []
        for i, doc in enumerate(docs):
            content = doc.get("content", "")[:500]
            prompt = f"""请判断以下文档与用户问题的相关程度，只返回一个 0-10 的整数分数。

用户问题：{query}

文档内容：{content}

相关度分数（0=完全不相关，10=高度相关）："""

            try:
                resp = await self.llm.generate([
                    ChatMessage(role="user", content=prompt),
                ])
                score_text = resp.content.strip()
                # 提取数字
                import re
                nums = re.findall(r"\d+", score_text)
                score = float(nums[0]) / 10.0 if nums else 0.5
            except Exception as e:
                logger.warning(f"LLM 打分失败 (doc {i}): {e}")
                score = doc.get("score", 0)

            doc["cross_encoder_score"] = round(score, 4)
            scored.append(doc)

        scored.sort(key=lambda x: x.get("cross_encoder_score", 0), reverse=True)
        k = top_k or len(scored)
        logger.info(f"LLM Cross-encoder 精排完成: {len(scored)} 篇 → Top-{k}")
        return scored[:k]

    @staticmethod
    def _rerank_fallback(docs: list[dict], top_k: Optional[int] = None) -> list[dict]:
        """兜底：使用原始分数排序"""
        docs.sort(key=lambda x: x.get("score", 0), reverse=True)
        k = top_k or len(docs)
        return docs[:k]
