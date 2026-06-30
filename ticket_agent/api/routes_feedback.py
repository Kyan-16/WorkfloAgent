"""
反馈与模式管理路由

提供工单反馈提交/统计、处理模式管理等接口。
"""
import logging
import threading

from fastapi import APIRouter, HTTPException, Query, Depends

from ticket_agent.api.schemas import (
    FeedbackRequest,
    FeedbackResponse,
    FeedbackStatsResponse,
    PatternResponse,
)
from ticket_agent.api.deps import get_coordinator
from ticket_agent.auth import require_any_role, require_manager, CurrentUser
from ticket_agent.repository import get_ticket_repository
from ticket_agent.feedback.store import get_feedback_store, TicketFeedback
from ticket_agent.memory.pattern_extractor import get_pattern_store
from ticket_agent.evolution.feedback_loop import trigger_feedback_evolution

logger = logging.getLogger(__name__)
router = APIRouter(prefix="", tags=["反馈与模式"])


# ── 反馈系统 ──

@router.post("/feedback", response_model=FeedbackResponse, summary="提交工单反馈")
async def submit_feedback(
    req: FeedbackRequest,
    current_user: CurrentUser = Depends(require_any_role),
):
    """对已处理的工单提交反馈（评分/点赞点踩/评论）"""
    store = get_feedback_store()

    ticket = get_ticket_repository().get(req.ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"工单 {req.ticket_id} 不存在")

    existing = store.get_by_ticket(req.ticket_id)
    if existing:
        raise HTTPException(status_code=409, detail=f"工单 {req.ticket_id} 已有反馈")

    feedback = TicketFeedback(
        ticket_id=req.ticket_id,
        user_id=current_user.user_id,
        rating=req.rating,
        feedback_type=req.feedback_type,
        comment=req.comment,
    )
    store.add(feedback)
    logger.info(
        f"反馈已提交: {feedback.feedback_id} "
        f"ticket={req.ticket_id} rating={req.rating} type={req.feedback_type}"
    )

    # 低评分工单 → 触发进化 + 知识补全闭环
    if req.rating < 3:
        _trigger_low_rating_review(req.ticket_id, req.comment)
        trigger_feedback_evolution(req.ticket_id, req.rating, req.comment)

    return FeedbackResponse(
        feedback_id=feedback.feedback_id,
        ticket_id=feedback.ticket_id,
        user_id=feedback.user_id,
        rating=feedback.rating,
        feedback_type=feedback.feedback_type,
        comment=feedback.comment,
        created_at=feedback.created_at,
    )


def _trigger_low_rating_review(ticket_id: str, comment: str):
    """低评分工单触发复盘"""
    logger.info(f"低评分工单需复盘: {ticket_id} 评论: {comment}")
    threading.Thread(target=_async_review, args=(ticket_id,), daemon=True).start()


def _async_review(ticket_id: str):
    """异步复盘：标记为需人工复审"""
    try:
        fb = get_feedback_store().get_by_ticket(ticket_id)
        if fb:
            fb.resolved = False
            logger.info(f"工单 {ticket_id} 已标记为需人工复审")
    except Exception as e:
        logger.warning(f"复盘标记失败: {e}")


@router.get("/feedback/stats", response_model=FeedbackStatsResponse, summary="反馈统计")
async def get_feedback_stats(
    current_user: CurrentUser = Depends(require_any_role),
):
    """获取工单反馈统计数据"""
    return get_feedback_store().get_stats()


@router.get("/feedback", response_model=list[FeedbackResponse], summary="反馈列表")
async def list_feedback(
    limit: int = Query(50, description="返回数量"),
    offset: int = Query(0, description="偏移量"),
    feedback_type: str = Query(None, description="筛选类型: positive/negative/neutral"),
    current_user: CurrentUser = Depends(require_any_role),
):
    """获取反馈列表（可按类型筛选）"""
    items = get_feedback_store().list_all(
        limit=limit, offset=offset, feedback_type=feedback_type,
    )
    return [
        FeedbackResponse(
            feedback_id=fb.feedback_id,
            ticket_id=fb.ticket_id,
            user_id=fb.user_id,
            rating=fb.rating,
            feedback_type=fb.feedback_type,
            comment=fb.comment,
            created_at=fb.created_at,
        )
        for fb in items
    ]


# ── 工单模式管理 ──

@router.get("/patterns", response_model=list[PatternResponse], summary="工单处理模式列表")
async def list_patterns(
    category: str = Query(None, description="按分类过滤: IT/HR/财务/运维"),
    current_user: CurrentUser = Depends(require_any_role),
):
    """获取从已解决工单中提取的处理模式"""
    patterns = get_pattern_store().get_all(category)
    return [
        PatternResponse(
            pattern_id=p.pattern_id,
            category=p.category,
            problem_summary=p.problem_summary,
            solution=p.solution,
            keywords=p.keywords,
            confidence=p.confidence,
            frequency=p.frequency,
            source_tickets=p.source_tickets,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in patterns
    ]


@router.delete("/patterns/{pattern_id}", summary="删除工单模式")
async def delete_pattern(
    pattern_id: str,
    current_user: CurrentUser = Depends(require_manager),
):
    """删除一个工单处理模式（需要经理/管理员权限）"""
    if not get_pattern_store().delete(pattern_id):
        raise HTTPException(status_code=404, detail=f"模式 {pattern_id} 不存在")
    return {"success": True, "message": f"模式 {pattern_id} 已删除"}
