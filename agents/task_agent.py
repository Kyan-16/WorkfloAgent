"""
任务型 Agent

支持 Function Calling 的 Agent，实现 ReAct 循环：
1. 用户输入 -> LLM 思考
2. LLM 决定调用工具 -> 执行工具 -> 将结果返回给 LLM
3. 重复步骤 2 直到 LLM 给出最终回答
"""
import asyncio
import time
import logging
from typing import Optional

from llm.base import LLMBase, ChatMessage, LLMResponse
from memory.base import MemoryBase
from rag.retriever import Retriever
from tools.registry import ToolRegistry
from tools.base import ToolResult
from agents.base import AgentBase, AgentResponse
from agents.context_guard import trim_context
from utils.tracing import AgentTraceRecorder, llm_response_to_dict, messages_to_dict
from ticket_agent.monitoring.metrics import TOOL_CALLS_TOTAL, TOOL_CALL_DURATION
from ticket_agent.security.tool_guard import ToolGuard

logger = logging.getLogger(__name__)

_LLM_TIMEOUT = 120.0


class TaskAgent(AgentBase):
    """
    任务型 Agent（支持 Tool Calling）

    实现 ReAct 循环：思考 -> 调用工具 -> 观察 -> 再思考 -> 最终回答

    使用示例：
        registry = ToolRegistry()
        registry.add(WebSearchTool())
        registry.add(CodeExecutorTool())

        agent = TaskAgent(
            llm=llm,
            memory=LocalMemory(),
            tool_registry=registry,
            system_prompt="你是一个能使用工具的智能助手。",
            max_tool_rounds=5,
        )
        response = await agent.chat("帮我搜索今天的新闻")
    """

    def __init__(
        self,
        llm: LLMBase,
        memory: Optional[MemoryBase] = None,
        retriever: Optional[Retriever] = None,
        tool_registry: Optional[ToolRegistry] = None,
        system_prompt: str = "你是一个智能助手，可以使用工具来完成任务。",
        memory_window_size: int = 10,
        max_tool_rounds: int = 5,
    ):
        super().__init__(
            llm=llm,
            memory=memory,
            retriever=retriever,
            tool_registry=tool_registry,
            system_prompt=system_prompt,
            memory_window_size=memory_window_size,
        )
        self.max_tool_rounds = max_tool_rounds

    async def chat(
        self,
        user_input: str,
        session_id: str = "default",
        use_rag: bool = True,
        images: list[str] = None,
    ) -> AgentResponse:
        """
        带工具调用的对话入口

        实现 ReAct 循环：
        LLM 回复 -> 检查是否有 tool_calls -> 执行工具 -> 将结果传回 LLM -> 循环

        :param images: 多模态图片 URL 列表（可选）
        """
        start_time = time.time()
        images = images or []
        trace = AgentTraceRecorder(
            agent_type=type(self).__name__,
            session_id=session_id,
            user_input=user_input,
            metadata={"use_rag": use_rag, "max_tool_rounds": self.max_tool_rounds, "image_count": len(images)},
        )

        try:
            # 1. 构建消息列表
            messages = [ChatMessage(role="system", content=self.system_prompt)]

            # 2. RAG 检索（使用共享方法）
            rag_messages, sources = await self._retrieve_rag(user_input, use_rag, trace)
            messages.extend(rag_messages)

            # 3. 加载对话历史（使用共享方法）
            messages.extend(await self._load_history(session_id, trace))

            # 4. 添加用户输入（支持图片）
            messages.append(ChatMessage.user_message(content=user_input, images=images))

            # 5. 获取工具 Schema
            tools = self.tool_registry.get_function_schemas() if self.tool_registry else None
            trace.record("tools_available", {"tools": tools or []})

            # 6. 初始化安全守卫
            guard = ToolGuard(session_id=session_id)

            # 7. ReAct 循环
            all_tool_calls = []
            llm_response = None
            reached_limit = False

            for round_idx in range(self.max_tool_rounds):
                # 本轮开始前裁剪上下文（防止多轮后超窗口）
                model_name = getattr(self.llm, "model", "")
                trimmed_msgs = trim_context(messages, model_name=model_name)
                if len(trimmed_msgs) < len(messages):
                    logger.info(f"ReAct 第{round_idx+1}轮: 上下文裁剪 {len(messages)} → {len(trimmed_msgs)} 条")
                    messages = trimmed_msgs

                trace.record(
                    "llm_request",
                    {
                        "round": round_idx + 1,
                        "model": getattr(self.llm, "model", ""),
                        "message_count": len(messages),
                        "messages": messages_to_dict(messages),
                        "tools": tools or [],
                    },
                )
                llm_start = time.time()
                try:
                    llm_response = await asyncio.wait_for(
                        self.llm.generate(messages=messages, tools=tools),
                        timeout=_LLM_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.error(f"LLM 调用超时 (session={session_id}, round={round_idx + 1})")
                    raise TimeoutError(f"LLM 调用超时 (已等待 {_LLM_TIMEOUT}s)")

                if llm_response is None:
                    break

                trace.record(
                    "llm_response",
                    {
                        "round": round_idx + 1,
                        "elapsed_seconds": round(time.time() - llm_start, 3),
                        **llm_response_to_dict(llm_response),
                    },
                )

                if not llm_response.is_tool_call:
                    # LLM 给出了最终回答
                    break

                # 处理工具调用
                logger.info(f"[ReAct 第{round_idx + 1}轮] 工具调用: {len(llm_response.tool_calls)} 个")

                # 将 assistant 的 tool_calls 消息加入历史
                messages.append(ChatMessage(
                    role="assistant",
                    content=llm_response.content or "",
                    tool_calls=llm_response.tool_calls,
                ))

                # 逐个执行工具（含安全守卫检查）
                for tc in llm_response.tool_calls:
                    func_name = tc.get("function", {}).get("name", "")
                    func_args = tc.get("function", {}).get("arguments", "{}")
                    logger.info(f"  执行工具: {func_name}")
                    trace.record(
                        "tool_request",
                        {
                            "round": round_idx + 1,
                            "tool_call_id": tc.get("id", ""),
                            "tool": func_name,
                            "arguments": func_args,
                        },
                    )

                    # 安全守卫：检查工具权限和频率
                    allowed, reason = guard.check(func_name)
                    if not allowed:
                        logger.info(f"[SECURITY] {reason}")
                        result = ToolResult(success=False, error=f"[安全限制] {reason}")
                        guard.record(func_name, func_args, result.to_str())
                        # 给 LLM 返回受限信息，让其调整行为
                        messages.append(ChatMessage(
                            role="tool",
                            content=f"[安全限制] 工具 {func_name} 未执行: {reason}",
                            tool_call_id=tc.get("id", ""),
                            name=func_name,
                        ))
                        continue

                    tool_start = time.time()
                    result = await self.tool_registry.call_from_llm_response(tc)
                    guard.record(func_name, func_args, result.to_str())
                    tool_elapsed = round(time.time() - tool_start, 3)
                    TOOL_CALLS_TOTAL.labels(tool=func_name, success=str(result.success).lower()).inc()
                    TOOL_CALL_DURATION.labels(tool=func_name).observe(tool_elapsed)
                    trace.record(
                        "tool_response",
                        {
                            "round": round_idx + 1,
                            "tool_call_id": tc.get("id", ""),
                            "tool": func_name,
                            "elapsed_seconds": tool_elapsed,
                            "success": result.success,
                            "output": result.output,
                            "error": result.error,
                        },
                    )
                    all_tool_calls.append({
                        "tool": func_name,
                        "result": result.to_str()[:500],
                        "success": result.success,
                    })

                    # 将工具结果传回 LLM
                    messages.append(ChatMessage(
                        role="tool",
                        content=result.to_str(),
                        tool_call_id=tc.get("id", ""),
                        name=func_name,
                    ))
            else:
                # 达到最大轮次仍未结束
                reached_limit = True
                logger.warning(f"达到最大工具调用轮次 ({self.max_tool_rounds})")
                trace.record("tool_round_limit_reached", {"max_tool_rounds": self.max_tool_rounds})

            # 处理达到最大轮次但 LLM 仍在请求工具的情况
            if reached_limit and llm_response and llm_response.is_tool_call:
                llm_response = LLMResponse(
                    content=f"我已经进行了 {self.max_tool_rounds} 轮工具调用但尚未得出最终结论，"
                            f"请基于当前已有信息给出答复。",
                    finish_reason="stop",
                )

            if llm_response is None:
                raise RuntimeError("LLM 未返回响应")

            # 8. 保存对话历史（使用共享方法）
            await self._save_history(session_id, user_input, llm_response.content, trace)

            elapsed = time.time() - start_time

            response = AgentResponse(
                content=llm_response.content,
                tool_calls=all_tool_calls,
                sources=sources,
                tokens_used=llm_response.tokens_used,
                model=llm_response.model,
                session_id=session_id,
                elapsed_seconds=round(elapsed, 2),
                metadata={"trace_id": trace.trace_id},
            )
            trace.finish(response=response.to_dict())
            return response
        except Exception as e:
            trace.fail(e)
            raise
