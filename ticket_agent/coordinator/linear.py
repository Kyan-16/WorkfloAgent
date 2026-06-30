"""
线性编排协调器

按固定流程编排：分类 → RAG 检索 → 执行 → 汇总回复。
流程简单清晰，适合工单处理这种确定性强的场景。
"""
import logging
import time
import uuid
from typing import Optional

from llm.base import LLMBase
from memory.base import MemoryBase
from agents.base import AgentResponse
from rag.retriever import Retriever

from ticket_agent.models.ticket import Ticket, TicketCategory, TicketStatus
from ticket_agent.repository import get_ticket_repository
from ticket_agent.agents.classifier import TicketClassifierAgent
from ticket_agent.agents.executor import TicketExecutionAgent
from ticket_agent.knowledge import build_category_retriever, build_global_retriever
from ticket_agent.monitoring.metrics import (
    TICKET_PROCESSING_DURATION,
    TICKET_PROCESSING_TOTAL,
    AGENT_STEP_DURATION,
    RAG_ZERO_RESULT_TOTAL,
    RAG_RETRIEVAL_DURATION,
    RAG_RETRIEVAL_TOTAL,
)
from ticket_agent.database import session_scope
from ticket_agent.database.models import User, TicketRecord
from ticket_agent.knowledge.store import get_knowledge_store

logger = logging.getLogger(__name__)

CATEGORY_DEPT_MAP = {"IT": 1, "HR": 2, "财务": 3, "运维": 4}
APPROVAL_REQUIRED_CATEGORIES = {"HR", "财务"}


class LinearCoordinator:

    def __init__(
        self,
        llm: LLMBase,
        memory: Optional[MemoryBase] = None,
        rag_top_k: int = 5,
        max_tool_rounds: int = 5,
        use_qdrant: bool = False,
        qdrant_retriever: Optional[Retriever] = None,
        reranker: Optional['CrossEncoderReranker'] = None,
        # 各 Agent 角色独立 LLM（可选，为空则用全局 llm）
        classifier_llm: Optional[LLMBase] = None,
        executor_llm: Optional[LLMBase] = None,
    ):
        self.llm = llm
        self.memory = memory
        self.rag_top_k = rag_top_k
        self.use_qdrant = use_qdrant
        self.qdrant_retriever = qdrant_retriever
        self.reranker = reranker
        self._clarifications: dict = {}

        # 每个 Agent 可使用独立 LLM（如分类用小模型省钱，执行用大模型）
        classifier_llm = classifier_llm or llm
        executor_llm = executor_llm or llm

        self.classifier = TicketClassifierAgent(llm=classifier_llm, memory=memory)
        self.executor = TicketExecutionAgent(llm=executor_llm, memory=memory, max_tool_rounds=max_tool_rounds)

        self._retrievers: dict = {}
        self._cached_kb_version: int = -1

    # ── 追问：信息不足时主动澄清 ──

    async def _ask_clarification(self, user_input: str, category: str, session_id: str) -> str:
        from llm.base import ChatMessage
        prompt = f"""工单信息不足，请生成 1-2 个追问帮用户补充关键信息。
用户描述：{user_input}
初步分类：{category}
要求：选项引导、专业友好、只返回追问文本（不要额外文字）"""
        try:
            resp = await self.llm.generate([ChatMessage(role="user", content=prompt)])
            return resp.content.strip()
        except Exception:
            return ""

    def _get_clarified_input(self, session_id: str, new_input: str) -> dict | None:
        pending = self._clarifications.pop(session_id, None)
        if not pending:
            return None
        merged = f"【补充信息】{new_input}\n【之前的描述】{pending['partial']['user_input']}"
        return {"user_input": merged, "category": pending["partial"]["category"]}

    # ── 自动分配 ──

    def _auto_assign(self, category: str) -> dict:
        default = {"department_id": 0, "assigned_to": None, "assigned_name": ""}
        dept_id = CATEGORY_DEPT_MAP.get(category)
        if not dept_id:
            # "其他"类工单兜底给管理员处理
            try:
                with session_scope() as session:
                    from ticket_agent.database.models import User
                    admin = session.query(User).filter(User.role == "admin").first()
                    if admin:
                        logger.info(f"「{category}」类工单无对应部门，自动分配给管理员: {admin.name}")
                        return {"department_id": 0, "assigned_to": admin.id, "assigned_name": admin.name}
            except Exception as e:
                logger.warning(f"兜底分配管理员失败: {e}")
            return default
        try:
            with session_scope() as session:
                engineers = session.query(User).filter(
                    User.department_id == dept_id,
                    User.role.in_(["engineer", "manager"]),
                    User.is_active == True,
                ).all()
                if not engineers:
                    managers = session.query(User).filter(
                        User.department_id == dept_id, User.role == "manager", User.is_active == True,
                    ).all()
                    if managers:
                        return {"department_id": dept_id, "assigned_to": managers[0].id, "assigned_name": managers[0].name}
                    return default
                eng_load = []
                for eng in engineers:
                    count = session.query(TicketRecord).filter(
                        TicketRecord.assigned_to == eng.id, TicketRecord.status.in_(["待处理", "处理中"]),
                    ).count()
                    eng_load.append((count, eng))
                eng_load.sort(key=lambda x: x[0])
                best = eng_load[0][1]
                return {"department_id": dept_id, "assigned_to": best.id, "assigned_name": best.name}
        except Exception as e:
            logger.warning(f"自动分配失败: {e}")
            return default

    # ── 检索器 ──

    def _get_retriever(self, category: str):
        kb = get_knowledge_store()
        if kb.version != self._cached_kb_version:
            self._retrievers.clear()
            self._cached_kb_version = kb.version
        if category not in self._retrievers:
            self._retrievers[category] = build_category_retriever(
                category=category, use_qdrant=self.use_qdrant,
                qdrant_retriever=self.qdrant_retriever, top_k=self.rag_top_k,
                use_reranker=self.reranker is not None, reranker=self.reranker,
            )
        return self._retrievers[category]

    # ── 主流程 ──

    async def process(
        self,
        user_input: str,
        user_id: str = "",
        session_id: str = "default",
        images: list[str] = None,
        user_category: str = "",
    ) -> dict:
        start_time = time.time()
        trace_id = str(uuid.uuid4())
        agent_steps = []

        if user_category:
            # 用户指定了部门，跳过AI分类直接使用
            classification = {"category": user_category, "confidence": 1.0,
                              "summary": user_input[:50], "needs_human": False, "reason": "用户指定"}
            agent_steps.append({"step": "classify", "elapsed": 0, "result": classification})
            logger.info(f"用户指定部门: {user_category}")
        else:
            clarified = self._get_clarified_input(session_id, user_input)
            if clarified:
                user_input = clarified["user_input"]
                logger.info(f"[{session_id}] 用户补充信息，继续处理")

        ticket = Ticket(content=user_input, user_id=user_id, session_id=session_id, trace_id=trace_id)

        try:
            # ── 分类 ──
            logger.info(f"[{session_id}] 步骤1: 分类 Agent 开始")
            classify_start = time.time()
            classification = await self.classifier.classify(user_input, session_id)
            agent_steps.append({"step": "classify", "elapsed": round(time.time() - classify_start, 2), "result": classification})
            logger.info(f"分类结果: {classification}")

            cat_value = classification.get("category", "其他")
            for tc in TicketCategory:
                if tc.value == cat_value:
                    ticket.category = tc
                    break

            category = classification.get("category", "其他")
            assign = self._auto_assign(category)
            confidence = classification.get("confidence", 0)
            needs_human = classification.get("needs_human", False)

            # 追问：信息不足时主动澄清
            if confidence < 0.6 and not needs_human:
                clarification = await self._ask_clarification(user_input, category, session_id)
                if clarification:
                    logger.info(f"[{session_id}] 需要追问: {clarification[:50]}...")
                    self._clarifications[session_id] = {
                        "question": clarification, "partial": {
                            "category": category, "user_input": user_input,
                            "trace_id": trace_id, "classify_result": classification,
                        }}
                    return {"success": True, "needs_clarification": True, "question": clarification,
                            "trace_id": trace_id, "session_id": session_id, "category": category,
                            "elapsed_seconds": round(time.time() - start_time, 2)}

            # 转人工
            if needs_human:
                logger.info(f"分类 Agent 判定需转人工")
                ticket.status = TicketStatus.ESCALATED
                final_response = f"""您好，已收到您的工单。\n\n根据评估，您的问题需要转交人工客服处理。原因：{classification.get('reason', '工单较为复杂')}\n\n我们将尽快安排专人与您联系，预计响应时间 30 分钟内。感谢您的耐心等待！"""
                elapsed = round(time.time() - start_time, 2)
                ticket.agent_response = final_response
                get_ticket_repository().create(ticket)
                get_ticket_repository().update(ticket.ticket_id, status="已转人工",
                    department_id=assign.get("department_id", 0), assigned_to=assign.get("assigned_to"),
                    assigned_name=assign.get("assigned_name", ""), priority="normal")
                TICKET_PROCESSING_TOTAL.labels(category=category, result="escalated", auto_resolved="false").inc()
                return {"success": True, "ticket_id": ticket.ticket_id, "category": category,
                        "response": final_response, "trace_id": trace_id, "elapsed_seconds": elapsed,
                        "agent_steps": agent_steps, "auto_resolved": False}

            # ── RAG 检索 ──
            logger.info(f"[{session_id}] 步骤2: RAG 检索 Agent 开始")
            rag_start = time.time()
            category = classification.get("category", "其他")
            rag_context = ""
            rag_doc_count = 0

            if category in ["IT", "HR", "财务", "运维"]:
                try:
                    rag_elapsed = round(time.time() - rag_start, 2)
                    retriever = self._get_retriever(category)
                    docs = await retriever.retrieve(user_input)
                    has_result = len(docs) > 0
                    RAG_RETRIEVAL_TOTAL.labels(category=category, has_result=str(has_result).lower()).inc()
                    RAG_RETRIEVAL_DURATION.labels(category=category).observe(rag_elapsed)
                    if docs:
                        rag_doc_count = len(docs)
                        rag_context = Retriever.format_context(docs)
                        agent_steps.append({"step": "retrieve", "elapsed": rag_elapsed, "result": {
                            "category": category, "doc_count": rag_doc_count,
                            "routes": list(set(r.get("route") for doc in docs for r in (doc.get("metadata", {}).get("retrieval_routes") or []))),
                        }})
                        logger.info(f"检索到 {rag_doc_count} 篇相关文档")
                    else:
                        RAG_ZERO_RESULT_TOTAL.labels(category=category).inc()
                        agent_steps.append({"step": "retrieve", "elapsed": rag_elapsed, "result": {"category": category, "doc_count": 0}})
                        logger.info(f"未检索到相关文档")
                        # 知识缺口自动检测 + 自动补全
                        try:
                            from ticket_agent.evolution.knowledge_gap import KnowledgeGapDetector
                            from ticket_agent.evolution.feedback_loop import auto_fill_knowledge_gap

                            gap_detector = KnowledgeGapDetector(llm=self.llm)
                            gap = await gap_detector.detect_gap({
                                "rag_doc_count": 0,
                                "category": category,
                                "content": user_input,
                                "ticket_id": ticket.ticket_id or "",
                            })
                            if gap:
                                await auto_fill_knowledge_gap({
                                    "category": gap.category,
                                    "suggested_title": gap.suggested_title,
                                    "suggested_content": gap.suggested_content,
                                    "source_tickets": gap.source_tickets,
                                }, llm=self.llm)
                        except Exception as gap_err:
                            logger.warning(f"知识缺口检测异常: {gap_err}")
                except Exception as e:
                    logger.warning(f"RAG 检索失败: {e}")
                    agent_steps.append({"step": "retrieve", "elapsed": round(time.time() - rag_start, 2), "result": {"error": str(e), "doc_count": 0}})
            else:
                agent_steps.append({"step": "retrieve", "elapsed": 0, "result": {"category": category, "doc_count": 0, "skipped": True}})

            # ── 执行 ──
            logger.info(f"[{session_id}] 步骤3: 执行 Agent 开始")
            exec_start = time.time()
            execution_input = user_input
            context_parts = []
            if rag_context:
                context_parts.append(f"【知识库参考资料】\n{rag_context}")
            if context_parts:
                execution_input = f"【用户问题】\n{user_input}\n\n" + "\n\n".join(context_parts) + "\n\n请结合上述参考资料处理该工单。"

            exec_result = await self.executor.chat(execution_input, session_id=session_id, use_rag=False, images=images)
            agent_steps.append({"step": "execute", "elapsed": round(time.time() - exec_start, 2), "result": {
                "tool_calls_count": len(exec_result.tool_calls),
                "tool_calls": [{"tool": tc["tool"], "success": tc.get("success", True)} for tc in exec_result.tool_calls],
            }})
            logger.info(f"执行 Agent 完成，调用了 {len(exec_result.tool_calls)} 个工具")

            # ── 汇总回复 ──
            final_response = exec_result.content
            elapsed = round(time.time() - start_time, 2)
            needs_approval = category in APPROVAL_REQUIRED_CATEGORIES
            approval_status = "pending" if needs_approval else ""
            final_status = "待审批" if needs_approval else "待确认"

            ticket.agent_response = final_response
            ticket.status = TicketStatus.AWAITING_CONFIRM
            get_ticket_repository().create(ticket)
            get_ticket_repository().update(ticket.ticket_id, status=final_status,
                department_id=assign.get("department_id", 0), assigned_to=assign.get("assigned_to"),
                assigned_name=assign.get("assigned_name", ""), priority="normal",
                needs_approval=needs_approval, approval_status=approval_status)

            TICKET_PROCESSING_TOTAL.labels(category=category, result="success", auto_resolved="true").inc()
            TICKET_PROCESSING_DURATION.labels(category=category, result="success", coordinator="linear").observe(elapsed)

            return {"success": True, "ticket_id": ticket.ticket_id, "category": category,
                    "response": final_response, "trace_id": trace_id, "elapsed_seconds": elapsed,
                    "agent_steps": agent_steps, "auto_resolved": True}

        except Exception as e:
            elapsed = round(time.time() - start_time, 2)
            logger.error(f"工单处理异常: {e}", exc_info=True)
            fallback_response = f"""您好，已收到您的工单（编号：{ticket.ticket_id}）。\n\n由于系统处理异常，您的工单将转交人工客服优先处理。我们将在 30 分钟内安排专人与您联系。\n\n给您带来的不便敬请谅解！"""
            ticket.agent_response = fallback_response
            ticket.status = TicketStatus.ESCALATED
            get_ticket_repository().create(ticket)
            TICKET_PROCESSING_TOTAL.labels(category="其他", result="error", auto_resolved="false").inc()
            TICKET_PROCESSING_DURATION.labels(category="其他", result="error", coordinator="linear").observe(elapsed)
            return {"success": False, "ticket_id": ticket.ticket_id, "category": "其他",
                    "response": fallback_response, "trace_id": trace_id, "elapsed_seconds": elapsed,
                    "agent_steps": agent_steps, "error": str(e), "auto_resolved": False}
