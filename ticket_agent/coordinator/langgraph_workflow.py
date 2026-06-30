"""
LangGraph 工作流编排

使用 StateGraph 定义工单生命周期的状态机：
START → classify → [needs_human? → escalate | retrieve] → [need_tool? → execute | summarize] → END

相比线性编排，LangGraph 版本的优势：
1. 状态显式化，流程更清晰
2. 条件边实现灵活的路由决策
3. 可观测性更强，方便调试
"""
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from llm.base import LLMBase, ChatMessage
from agents.base import AgentResponse
from utils.tracing import AgentTraceRecorder

from ticket_agent.models.state import TicketState
from ticket_agent.agents.classifier import TicketClassifierAgent
from ticket_agent.agents.executor import TicketExecutionAgent
from ticket_agent.knowledge import build_category_retriever

from rag.retriever import Retriever
from ticket_agent.repository import get_ticket_repository
from ticket_agent.models.ticket import Ticket, TicketCategory, TicketStatus

logger = logging.getLogger(__name__)

# 尝试导入 LangGraph
try:
    from langgraph.graph import END, START, StateGraph
    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False
    logger.warning("langgraph 未安装，LangGraph 工作流不可用")


class LangGraphCoordinator:
    """
    LangGraph 工单编排器

    使用方式：
        coordinator = LangGraphCoordinator(llm=llm)
        result = await coordinator.run("电脑蓝屏了")
    """

    def __init__(
        self,
        llm: LLMBase,
        memory=None,
        rag_top_k: int = 5,
        max_tool_rounds: int = 5,
    ):
        if not HAS_LANGGRAPH:
            raise ImportError("langgraph 未安装，请运行: pip install langgraph")

        self.llm = llm
        self.memory = memory
        self.rag_top_k = rag_top_k

        # 初始化 Agent
        self.classifier = TicketClassifierAgent(llm=llm, memory=memory)
        self.executor = TicketExecutionAgent(
            llm=llm, memory=memory, max_tool_rounds=max_tool_rounds,
        )

        self._retrievers: dict = {}
        self.graph = self._build_graph()

    def _get_retriever(self, category: str):
        if category not in self._retrievers:
            self._retrievers[category] = build_category_retriever(category=category, top_k=self.rag_top_k)
        return self._retrievers[category]

    def _build_graph(self) -> "StateGraph":
        """构建 LangGraph 状态图"""
        graph = StateGraph(TicketState)

        graph.add_node("classify_node", self._classify_node)
        graph.add_node("retrieve_node", self._retrieve_node)
        graph.add_node("execute_node", self._execute_node)
        graph.add_node("summarize_node", self._summarize_node)
        graph.add_node("escalate_node", self._escalate_node)

        graph.add_edge(START, "classify_node")

        graph.add_conditional_edges(
            "classify_node",
            self._route_after_classify,
            {"retrieve": "retrieve_node", "escalate": "escalate_node"},
        )

        graph.add_conditional_edges(
            "retrieve_node",
            self._route_after_retrieve,
            {"execute": "execute_node", "summarize": "summarize_node"},
        )

        graph.add_edge("execute_node", "summarize_node")
        graph.add_edge("summarize_node", END)
        graph.add_edge("escalate_node", END)

        return graph.compile()

    async def _classify_node(self, state: TicketState) -> dict:
        """分类节点"""
        result = await self.classifier.classify(state["user_input"], state.get("session_id", "default"))
        return {
            "category": result.get("category", "其他"),
            "confidence": result.get("confidence", 0.0),
            "needs_human": result.get("needs_human", False),
            "classification_reason": result.get("reason", ""),
        }

    def _route_after_classify(self, state: TicketState) -> str:
        return "escalate" if state.get("needs_human") else "retrieve"

    async def _retrieve_node(self, state: TicketState) -> dict:
        """RAG 检索节点"""
        category = state.get("category", "其他")
        if category not in ["IT", "HR", "财务", "运维"]:
            return {"rag_context": "", "retrieved_docs": []}

        try:
            retriever = self._get_retriever(category)
            docs = await retriever.retrieve(state["user_input"])
            if docs:
                context = Retriever.format_context(docs)
                return {"rag_context": context, "retrieved_docs": docs}
        except Exception as e:
            logger.warning(f"检索失败: {e}")

        return {"rag_context": "", "retrieved_docs": []}

    def _route_after_retrieve(self, state: TicketState) -> str:
        has_context = bool(state.get("rag_context"))
        return "execute" if has_context else "summarize"

    async def _execute_node(self, state: TicketState) -> dict:
        """执行节点（ReAct 工具循环）"""
        user_input = state["user_input"]
        rag_context = state.get("rag_context", "")
        session_id = state.get("session_id", "default")

        if rag_context:
            execution_input = (
                f"【用户问题】\n{user_input}\n\n"
                f"【知识库参考资料】\n{rag_context}\n\n"
                f"请结合上述参考资料处理该工单。"
            )
        else:
            execution_input = user_input

        result = await self.executor.chat(execution_input, session_id=session_id, use_rag=False)
        return {
            "tool_calls": [
                {"tool": tc["tool"], "success": tc.get("success", True)}
                for tc in result.tool_calls
            ],
            "tool_results": result.tool_calls,
        }

    async def _summarize_node(self, state: TicketState) -> dict:
        """汇总回复节点"""
        messages = [
            ChatMessage(role="system", content="你是一个工单处理助手。请基于已有信息生成最终回复。"),
            ChatMessage(role="user", content=(
                f"用户问题：{state['user_input']}\n\n"
                f"工单分类：{state.get('category', '未知')}\n\n"
                f"{'参考资料：' + state['rag_context'] if state.get('rag_context') else '（无参考资料）'}\n\n"
                f"{'工具执行结果：' + json.dumps(state.get('tool_calls', []), ensure_ascii=False) if state.get('tool_calls') else ''}\n\n"
                f"请生成对用户的最终回复。"
            )),
        ]
        response = await self.llm.generate(messages)
        return {"final_response": response.content}

    async def _escalate_node(self, state: TicketState) -> dict:
        """转人工节点"""
        reason = state.get("classification_reason", "工单需人工处理")
        return {
            "final_response": f"""您好，已收到您的工单。

根据评估，您的问题需要转交人工客服处理。原因：{reason}

我们将尽快安排专人与您联系，预计响应时间 30 分钟内。感谢您的耐心等待！""",
        }

    async def run(self, user_input: str, session_id: str = "default", user_id: str = "") -> dict:
        """
        执行 LangGraph 工作流

        Returns: 与 LinearCoordinator.process() 相同格式的结果
        """
        start_time = time.time()
        trace_id = str(uuid.uuid4())
        ticket_id = f"TK-{time.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

        try:
            initial_state: TicketState = {
                "user_input": user_input,
                "session_id": session_id,
                "user_id": user_id,
                "category": "",
                "confidence": 0.0,
                "needs_human": False,
                "classification_reason": "",
                "retrieved_docs": [],
                "rag_context": "",
                "tool_calls": [],
                "tool_results": [],
                "final_response": "",
                "trace_id": trace_id,
                "error": None,
                "retry_count": 0,
            }

            final_state = await self.graph.ainvoke(initial_state)

            elapsed = round(time.time() - start_time, 2)

            # 持久化到数据库

            final_response = final_state.get("final_response", "处理完成")
            category_str = final_state.get("category", "其他")
            category_enum = None
            for tc in TicketCategory:
                if tc.value == category_str:
                    category_enum = tc
                    break

            ticket = Ticket(
                content=user_input,
                user_id=user_id or "anonymous",
                category=category_enum,
                status=TicketStatus.ESCALATED if final_state.get("needs_human") else TicketStatus.RESOLVED,
                agent_response=final_response,
                trace_id=trace_id,
            )
            # 覆写生成的 ticket_id 为统一格式
            ticket.ticket_id = ticket_id
            get_ticket_repository().create(ticket)

            return {
                "success": True,
                "ticket_id": ticket_id,
                "category": category_str,
                "response": final_response,
                "trace_id": trace_id,
                "elapsed_seconds": elapsed,
                "agent_steps": [
                    {"step": "classify", "result": final_state.get("category")},
                    {"step": "retrieve", "result": f"检索到 {len(final_state.get('retrieved_docs', []))} 篇文档" if final_state.get("retrieved_docs") else "未检索"},
                    {"step": "execute/respond", "result": f"调用了 {len(final_state.get('tool_calls', []))} 个工具" if final_state.get("tool_calls") else "直接回答"},
                ],
                "auto_resolved": not final_state.get("needs_human", False),
            }

        except Exception as e:
            elapsed = round(time.time() - start_time, 2)
            logger.error(f"LangGraph 工作流异常: {e}", exc_info=True)

            # 异常时也写入 DB

            ticket = Ticket(
                content=user_input,
                user_id=user_id or "anonymous",
                status=TicketStatus.ESCALATED,
                agent_response=f"系统处理异常，已转人工（错误: {str(e)}）",
                trace_id=trace_id,
            )
            ticket.ticket_id = ticket_id
            get_ticket_repository().create(ticket)

            return {
                "success": False,
                "ticket_id": ticket_id,
                "category": "其他",
                "response": f"您好，系统处理异常，您的工单已转人工处理（错误: {str(e)}）",
                "trace_id": trace_id,
                "elapsed_seconds": elapsed,
                "agent_steps": [],
                "error": str(e),
                "auto_resolved": False,
            }
