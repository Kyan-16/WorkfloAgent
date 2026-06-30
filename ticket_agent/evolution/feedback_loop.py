"""
反馈闭环 — 将用户反馈接入自我进化系统

实现两个闭环：
1. 差评 → 触发进化 → 更新 MEMORY.md → 下次回答更好
2. 知识缺口 → LLM 生成草稿 → 自动入库 → 知识库自增长

使用方式：
    # 在 feedback 提交后调用
    await process_negative_feedback(ticket_id, rating, comment, llm)

    # 在 RAG 零结果后调用
    await process_knowledge_gap(ticket_data, llm)
"""
import asyncio
import logging
import threading
from typing import Optional

from llm.base import LLMBase, ChatMessage

logger = logging.getLogger(__name__)


# ── 1. 差评 → 进化闭环 ──

async def process_negative_feedback(
    ticket_id: str,
    rating: int,
    comment: str,
    llm: Optional[LLMBase] = None,
):
    """
    差评反馈处理：触发进化 + 知识缺口检测。

    当用户评分为 1-2 分时自动调用。
    流程：审查对话 → 更新 MEMORY.md → 检测知识缺口
    """
    logger.info(f"[反馈闭环] 开始处理差评工单: {ticket_id} (评分={rating})")

    # 获取工单数据
    from ticket_agent.repository import get_ticket_repository

    repo = get_ticket_repository()
    ticket = repo.get(ticket_id)
    if not ticket:
        logger.warning(f"[反馈闭环] 工单不存在: {ticket_id}")
        return

    user_input = getattr(ticket, "content", "") or ticket.get("content", "")
    agent_response = getattr(ticket, "agent_response", "") or ticket.get("agent_response", "")
    category = getattr(ticket, "category", "") or ticket.get("category", "")

    if not user_input:
        logger.warning(f"[反馈闭环] 工单内容为空: {ticket_id}")
        return

    if llm is None:
        # 尝试从 coordinator 获取 LLM
        try:
            from ticket_agent.api.deps import get_coordinator
            coord = get_coordinator()
            llm = coord.llm
        except Exception:
            logger.warning("[反馈闭环] 无法获取 LLM 实例，跳过")
            return

    # 步骤 1：触发进化（Review Agent 审查）
    try:
        from ticket_agent.evolution.executor import EvolutionExecutor
        from ticket_agent.memory.storage import MemoryStore

        store = MemoryStore()
        current_memory = store.load_memory()

        executor = EvolutionExecutor(llm=llm, store=store)
        review_content = f"用户问题：{user_input}\nAgent 回复：{agent_response}\n用户反馈：评分 {rating}/5，评论：{comment}"

        result = await executor.try_evolve(
            topic=f"[差评复盘] {category} - {user_input[:50]}",
            content=review_content,
            current_memory=current_memory,
            force=True,  # 差评强制触发进化
        )
        logger.info(f"[反馈闭环] 进化结果: {result}")
    except Exception as e:
        logger.error(f"[反馈闭环] 进化失败: {e}")

    # 步骤 2：自动生成知识库文档（如果 LLM 有建议）
    try:
        from ticket_agent.knowledge.store import get_knowledge_store

        kb = get_knowledge_store()

        # 用 LLM 生成本问题的知识文档
        prompt = f"""你是一个知识库编辑专家。根据以下工单信息，生成一篇知识库文档。

工单分类：{category}
用户问题：{user_input}
Agent 回复：{agent_response}
用户反馈：评分 {rating}/5，评论：{comment}

请生成 JSON：
{{
  "title": "文档标题（简洁概括问题）",
  "content": "文档内容（包含问题描述、排查步骤、解决方案，100-200字）"
}}

要求：内容准确、步骤清晰、对后续处理同类工单有实际帮助。"""

        resp = await llm.generate([ChatMessage(role="user", content=prompt)], temperature=0.3, max_tokens=1024)

        from utils.json_parser import safe_parse_json
        result_data = safe_parse_json(resp.content, default=None)

        if result_data and result_data.get("content"):
            title = result_data.get("title", f"[{category}] 待补充文档")
            content = result_data.get("content", "")

            # 检查是否已存在相似文档
            existing_docs = kb.list_docs(category=category)
            is_duplicate = False
            for doc in existing_docs:
                if len(set(content.split()) & set(doc.get("content", "").split())) > 10:
                    is_duplicate = True
                    break

            if not is_duplicate:
                doc = kb.add_doc(
                    content=content,
                    category=category,
                    source=f"差评自动生成 (ticket={ticket_id})",
                )
                logger.info(f"[反馈闭环] 知识库文档自动生成: {doc.get('doc_id', '')} - {title}")

                # 标记相关知识缺口为已解决
                from ticket_agent.evolution.knowledge_gap import get_gap_store
                gap_store = get_gap_store()
                for gap in gap_store.list_unresolved(category):
                    if gap.suggested_title == title or any(kw in content for kw in gap.keywords):
                        gap_store.mark_resolved(gap.gap_id)
                        logger.info(f"[反馈闭环] 知识缺口已解决: {gap.gap_id}")
            else:
                logger.info("[反馈闭环] 相似文档已存在，跳过自动生成")
    except Exception as e:
        logger.warning(f"[反馈闭环] 知识库文档生成失败: {e}")


# ── 2. 知识缺口 → 自动补全闭环 ──

async def auto_fill_knowledge_gap(
    gap_data: dict,
    llm: Optional[LLMBase] = None,
    auto_approve: bool = True,
) -> Optional[dict]:
    """
    自动补全知识缺口。

    当 KnowledgeGapDetector 发现缺口时调用。

    Args:
        gap_data: 缺口数据（含 category, suggested_title, suggested_content, source_tickets）
        llm: LLM 实例
        auto_approve: 是否自动入库（False 则只生成草稿）

    Returns:
        生成的文档 dict，或 None
    """
    if llm is None:
        try:
            from ticket_agent.api.deps import get_coordinator
            coord = get_coordinator()
            llm = coord.llm
        except Exception:
            logger.warning("[知识缺口] 无法获取 LLM 实例，跳过")
            return None

    category = gap_data.get("category", "")
    suggested_title = gap_data.get("suggested_title", "")
    suggested_content = gap_data.get("suggested_content", "")
    source_tickets = gap_data.get("source_tickets", [])

    if not category:
        logger.warning("[知识缺口] 分类为空，跳过")
        return None

    # 如果已有建议内容，直接使用；否则让 LLM 生成
    if suggested_content and len(suggested_content) > 20:
        content = suggested_content
        title = suggested_title or f"[{category}] 自动生成文档"
    else:
        try:
            # 从关联工单提取上下文
            from ticket_agent.repository import get_ticket_repository
            repo = get_ticket_repository()

            ticket_contexts = []
            for tid in source_tickets[:3]:
                ticket = repo.get(tid)
                if ticket:
                    c = getattr(ticket, "content", "") or ticket.get("content", "")
                    ticket_contexts.append(c)

            context = "\n".join(ticket_contexts) if ticket_contexts else "无历史工单"

            prompt = f"""知识库缺少以下分类的文档，请根据用户提的问题生成一篇知识库文档。

分类：{category}
建议标题：{suggested_title}
关联工单：{context}

输出 JSON：
{{{{
  "title": "文档标题",
  "content": "文档内容（包含问题描述、排查步骤、解决方案，100-200字）"
}}}}"""
            resp = await llm.generate([ChatMessage(role="user", content=prompt)], temperature=0.3, max_tokens=1024)

            from utils.json_parser import safe_parse_json
            result_data = safe_parse_json(resp.content, default=None)
            if not result_data or not result_data.get("content"):
                logger.warning("[知识缺口] LLM 生成内容为空")
                return None

            content = result_data["content"]
            title = result_data.get("title", suggested_title or f"[{category}] 自动生成文档")
        except Exception as e:
            logger.error(f"[知识缺口] LLM 生成失败: {e}")
            return None

    if auto_approve:
        from ticket_agent.knowledge.store import get_knowledge_store
        kb = get_knowledge_store()

        doc = kb.add_doc(
            content=content,
            category=category,
            source=f"知识缺口自动补全 ({','.join(source_tickets[:3])})",
        )

        # 标记缺口为已解决
        from ticket_agent.evolution.knowledge_gap import get_gap_store
        gap_store = get_gap_store()
        for gap in gap_store.list_unresolved(category):
            if any(kw in content for kw in gap.keywords):
                gap_store.mark_resolved(gap.gap_id)
                logger.info(f"[知识缺口] 已解决并入库: {gap.gap_id}")

        logger.info(f"[知识缺口] 文档已自动入库: {doc.get('doc_id', '')} - {title}")
        return doc
    else:
        logger.info(f"[知识缺口] 文档已生成（待人工确认）: {title}")
        return {"title": title, "content": content, "status": "draft"}


# ── 异步触发便捷函数 ──

def trigger_feedback_evolution(
    ticket_id: str,
    rating: int,
    comment: str,
    llm=None,
):
    """
    异步触发反馈进化（不阻塞当前请求）。

    在 feedback API 端点中调用。
    """
    async def _run():
        await process_negative_feedback(ticket_id, rating, comment, llm)

    threading.Thread(
        target=lambda: asyncio.run(_run()),
        daemon=True,
    ).start()
