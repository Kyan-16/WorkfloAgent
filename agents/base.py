"""
Agent 基类

组合 LLM + Memory + RAG + Tools，提供统一的 Agent 生命周期管理。
"""
import time
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional

from llm.base import LLMBase, ChatMessage, LLMResponse
from memory.base import MemoryBase
from rag.retriever import Retriever
from tools.registry import ToolRegistry
from utils.tracing import AgentTraceRecorder, llm_response_to_dict, messages_to_dict
from agents.context_guard import trim_context

logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    """Agent 响应结构"""
    content: str = ""
    tool_calls: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    tokens_used: int = 0
    model: str = ""
    session_id: str = ""
    elapsed_seconds: float = 0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "content": self.content, "sources": self.sources,
            "tokens_used": self.tokens_used, "model": self.model,
            "session_id": self.session_id, "elapsed_seconds": self.elapsed_seconds,
            "metadata": self.metadata,
        }


class AgentBase:

    def __init__(
        self,
        llm: LLMBase,
        memory: Optional[MemoryBase] = None,
        retriever: Optional[Retriever] = None,
        tool_registry: Optional[ToolRegistry] = None,
        system_prompt: str = "你是一个智能助手。",
        memory_window_size: int = 10,
    ):
        self.llm = llm
        self.memory = memory
        self.retriever = retriever
        self.tool_registry = tool_registry
        self.system_prompt = system_prompt
        self.memory_window_size = memory_window_size

    async def _retrieve_rag(self, user_input: str, use_rag: bool, trace: AgentTraceRecorder) -> tuple[list[ChatMessage], list[dict]]:
        """RAG 检索：返回 (注入的 system 消息列表, sources 列表)"""
        sources = []
        rag_messages = []
        if use_rag and self.retriever:
            rag_start = time.time()
            docs = await self.retriever.retrieve(user_input)
            trace.record("rag_retrieve", {
                "elapsed_seconds": round(time.time() - rag_start, 3),
                "doc_count": len(docs), "docs": docs,
            })
            if docs:
                context = Retriever.format_context(docs)
                rag_messages.append(ChatMessage(role="system", content=f"【参考资料】\n{context}\n\n请结合上述参考资料回答用户问题。"))
                sources = [{"content": d["content"][:200], "score": d.get("score", 0), "metadata": d.get("metadata", {})} for d in docs]
        return rag_messages, sources

    async def _load_history(self, session_id: str, trace: AgentTraceRecorder) -> list[ChatMessage]:
        """加载对话历史"""
        history_messages = []
        if self.memory:
            history = await self.memory.get_history(session_id, limit=self.memory_window_size)
            trace.record("memory_load", {
                "history_count": len(history), "limit": self.memory_window_size,
                "messages": [{"role": msg.role, "content": msg.content} for msg in history],
            })
            for msg in history:
                history_messages.append(ChatMessage(role=msg.role, content=msg.content))
        return history_messages

    async def _save_history(self, session_id: str, user_input: str, response_content: str, trace: AgentTraceRecorder):
        """保存对话历史"""
        if self.memory:
            await self.memory.add(session_id, "user", user_input)
            await self.memory.add(session_id, "assistant", response_content)
            trace.record("memory_save", {"messages_saved": 2})

    async def chat(
        self,
        user_input: str,
        session_id: str = "default",
        use_rag: bool = True,
        images: list[str] = None,
    ) -> AgentResponse:
        if not user_input or not user_input.strip():
            raise ValueError("user_input 不能为空")
        if len(user_input) > 32000:
            raise ValueError(f"user_input 过长 ({len(user_input)} 字符)")
        if not session_id or not session_id.strip():
            raise ValueError("session_id 不能为空")
        start_time = time.time()
        images = images or []
        trace = AgentTraceRecorder(
            agent_type=type(self).__name__, session_id=session_id,
            user_input=user_input, metadata={"use_rag": use_rag, "image_count": len(images)},
        )
        try:
            messages = [ChatMessage(role="system", content=self.system_prompt)]
            rag_messages, sources = await self._retrieve_rag(user_input, use_rag, trace)
            messages.extend(rag_messages)
            messages.extend(await self._load_history(session_id, trace))
            messages.append(ChatMessage.user_message(content=user_input, images=images))

            # 上下文窗口管理：超阈值自动裁剪
            model_name = getattr(self.llm, "model", "")
            trimmed = trim_context(messages, model_name=model_name)
            if len(trimmed) < len(messages):
                logger.info(f"上下文已裁剪: {len(messages)} → {len(trimmed)} 条")
                messages = trimmed

            trace.record("llm_request", {"model": model_name, "message_count": len(messages), "messages": messages_to_dict(messages), "tools": []})
            llm_start = time.time()
            llm_response = await asyncio.wait_for(self.llm.generate(messages=messages), timeout=120.0)
            trace.record("llm_response", {"elapsed_seconds": round(time.time() - llm_start, 3), **llm_response_to_dict(llm_response)})

            await self._save_history(session_id, user_input, llm_response.content, trace)

            elapsed = time.time() - start_time
            response = AgentResponse(
                content=llm_response.content, sources=sources, tokens_used=llm_response.tokens_used,
                model=llm_response.model, session_id=session_id, elapsed_seconds=round(elapsed, 2),
                metadata={"trace_id": trace.trace_id},
            )
            trace.finish(response=response.to_dict())
            return response
        except Exception as e:
            trace.fail(e)
            raise
