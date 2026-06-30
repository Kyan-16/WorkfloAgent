"""
SSE 事件流

将工单处理过程包装为 SSE（Server-Sent Events）流，
每个处理阶段作为一个独立事件推送。

事件类型：
- step: 处理步骤通知（分类/检索/执行/回复）
- tool: 工具调用通知
- message: 最终回复内容
- error: 错误信息
- complete: 处理完成
"""
import asyncio
import json
import logging
import time
import uuid
from typing import AsyncGenerator, Optional

from llm.base import LLMBase

logger = logging.getLogger(__name__)


class SSEEvent:
    """SSE 事件"""

    def __init__(self, event_type: str, data: dict):
        self.event_type = event_type
        self.data = data

    def format(self) -> str:
        """格式化为 SSE 协议文本"""
        lines = []
        if self.event_type:
            lines.append(f"event: {self.event_type}")
        lines.append(f"data: {json.dumps(self.data, ensure_ascii=False)}")
        lines.append("")
        return "\n".join(lines)


class SSETicketStream:
    """
    工单处理流式执行器

    包裹 LinearCoordinator 的 process 方法，将每个步骤通过 SSE 事件推送。

    使用示例：
        stream = SSETicketStream(coordinator)
        async for chunk in stream.process("电脑蓝屏了"):
            yield chunk
    """

    def __init__(self, coordinator, llm: Optional[LLMBase] = None):
        self.coordinator = coordinator
        self.llm = llm
        self._start_time = 0

    async def process(
        self,
        user_input: str,
        session_id: str = "default",
        user_id: str = "",
        images: list[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式处理工单

        Yields SSE 格式的字符串事件
        """
        self._start_time = time.time()
        trace_id = str(uuid.uuid4())
        agent_steps = []

        try:
            # ── 步骤1: 分类 ──
            yield SSEEvent("step", {
                "step": "classify",
                "status": "start",
                "message": "正在分析工单内容...",
                "trace_id": trace_id,
            }).format()

            classify_start = time.time()
            classification = await self.coordinator.classifier.classify(user_input, session_id)
            classify_elapsed = round(time.time() - classify_start, 2)
            agent_steps.append({
                "step": "classify",
                "elapsed": classify_elapsed,
                "result": classification,
            })

            category = classification.get("category", "其他")
            needs_human = classification.get("needs_human", False)

            yield SSEEvent("step", {
                "step": "classify",
                "status": "complete",
                "category": category,
                "confidence": classification.get("confidence", 0),
                "needs_human": needs_human,
                "summary": classification.get("summary", ""),
                "elapsed": classify_elapsed,
            }).format()

            if needs_human:
                yield SSEEvent("step", {
                    "step": "escalate",
                    "status": "start",
                    "message": "该工单需要转交人工处理...",
                    "reason": classification.get("reason", "工单较为复杂"),
                }).format()

                result = {
                    "success": True,
                    "category": category,
                    "response": f"您好，已收到您的工单。\n\n根据评估，您的问题需要转交人工客服处理。原因：{classification.get('reason', '工单较为复杂')}\n\n我们将尽快安排专人与您联系，预计响应时间 30 分钟内。",
                    "trace_id": trace_id,
                    "elapsed_seconds": round(time.time() - self._start_time, 2),
                    "agent_steps": agent_steps,
                    "auto_resolved": False,
                }
                yield SSEEvent("complete", result).format()
                return

            # ── 步骤2: RAG 检索 ──
            yield SSEEvent("step", {
                "step": "retrieve",
                "status": "start",
                "message": f"正在从 [{category}] 知识库检索解决方案...",
            }).format()

            rag_start = time.time()
            rag_context = ""
            retrieved_docs = []

            if category in ["IT", "HR", "财务", "运维"]:
                try:
                    retriever = self.coordinator._get_retriever(category)
                    docs = await retriever.retrieve(user_input)
                    retrieved_docs = docs or []
                    if retrieved_docs:
                        from rag.retriever import Retriever
                        rag_context = Retriever.format_context(retrieved_docs)
                        yield SSEEvent("step", {
                            "step": "retrieve",
                            "status": "complete",
                            "doc_count": len(retrieved_docs),
                            "elapsed": round(time.time() - rag_start, 2),
                        }).format()
                    else:
                        yield SSEEvent("step", {
                            "step": "retrieve",
                            "status": "empty",
                            "message": "未检索到相关文档",
                        }).format()
                except Exception as e:
                    logger.warning(f"检索失败: {e}")
                    yield SSEEvent("step", {
                        "step": "retrieve",
                        "status": "error",
                        "message": f"检索过程出现异常",
                    }).format()
            else:
                yield SSEEvent("step", {
                    "step": "retrieve",
                    "status": "skipped",
                    "message": f"分类 [{category}] 无需知识库检索",
                }).format()

            agent_steps.append({
                "step": "retrieve",
                "elapsed": round(time.time() - rag_start, 2),
                "result": {"doc_count": len(retrieved_docs)},
            })

            # ── 步骤3: 执行 Agent ──
            yield SSEEvent("step", {
                "step": "execute",
                "status": "start",
                "message": "正在处理您的工单...",
            }).format()

            exec_start = time.time()
            execution_input = user_input
            if rag_context:
                execution_input = (
                    f"【用户问题】\n{user_input}\n\n"
                    f"【知识库参考资料】\n{rag_context}\n\n"
                    f"请结合上述参考资料处理该工单。"
                )

            exec_result = await self.coordinator.executor.chat(
                execution_input,
                session_id=session_id,
                use_rag=False,
                images=images,
            )

            # 推送工具调用事件
            for tc in exec_result.tool_calls:
                yield SSEEvent("tool", {
                    "tool": tc.get("tool", ""),
                    "success": tc.get("success", True),
                    "result": str(tc.get("result", ""))[:200],
                }).format()

            yield SSEEvent("step", {
                "step": "execute",
                "status": "complete",
                "tool_calls": len(exec_result.tool_calls),
                "elapsed": round(time.time() - exec_start, 2),
            }).format()

            agent_steps.append({
                "step": "execute",
                "elapsed": round(time.time() - exec_start, 2),
                "result": {"tool_calls_count": len(exec_result.tool_calls)},
            })

            # ── 步骤4: 回复 ──
            final_response = exec_result.content
            elapsed = round(time.time() - self._start_time, 2)

            result = {
                "success": True,
                "category": category,
                "response": final_response,
                "trace_id": trace_id,
                "elapsed_seconds": elapsed,
                "agent_steps": agent_steps,
                "auto_resolved": True,
            }

            yield SSEEvent("message", {
                "content": final_response,
            }).format()

            yield SSEEvent("complete", result).format()

        except Exception as e:
            logger.error(f"SSE 流处理异常: {e}", exc_info=True)
            elapsed = round(time.time() - self._start_time, 2)
            yield SSEEvent("error", {
                "message": f"处理异常: {str(e)}",
                "trace_id": trace_id,
            }).format()
            yield SSEEvent("complete", {
                "success": False,
                "error": str(e),
                "trace_id": trace_id,
                "elapsed_seconds": elapsed,
                "auto_resolved": False,
            }).format()
