"""
工单处理路由

提供工单 CRUD、提票、流式处理、追踪查询等接口。
"""
import json
import logging
import os
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ticket_agent.api.schemas import (
    TicketRequest,
    TicketResponse,
    TicketInfoResponse,
    AgentStep,
    StreamTicketRequest,
    ResolveRequest,
)
from ticket_agent.api.deps import get_coordinator
from ticket_agent.repository import get_ticket_repository
from ticket_agent.auth import get_current_user, require_any_role, require_engineer, CurrentUser
from ticket_agent.database import session_scope
from ticket_agent.database.models import TicketRecord
from ticket_agent.streaming.event_stream import SSETicketStream

logger = logging.getLogger(__name__)
router = APIRouter(prefix="", tags=["工单处理"])


# ── 工单操作：工程师接单 ──

@router.post("/ticket/{ticket_id}/assign", summary="工程师接单")
async def assign_ticket(
    ticket_id: str,
    current_user: CurrentUser = Depends(require_engineer),
):
    """工程师接单：将工单分配给自己处理。"""
    ticket = get_ticket_repository().get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"工单 {ticket_id} 不存在")

    if ticket.status.value not in ("待处理", "待确认", "待审批", "已转人工"):
        raise HTTPException(
            status_code=400,
            detail=f"工单当前状态为「{ticket.status.value}」，不可接单（仅待处理/待确认/待审批/已转人工可接单）",
        )

    result = get_ticket_repository().update(
        ticket_id,
        status="处理中",
        assigned_to=current_user.id,
        assigned_name=current_user.name,
    )
    if not result:
        raise HTTPException(status_code=500, detail="接单失败")

    logger.info(f"工单 {ticket_id} 已被 {current_user.name}({current_user.user_id}) 接单")
    return {"success": True, "message": f"工单 {ticket_id} 已分配给 {current_user.name}", "ticket_id": ticket_id}


# ── 工单操作：标记完成 ──

@router.post("/ticket/{ticket_id}/resolve", summary="标记工单为已解决")
async def resolve_ticket(
    ticket_id: str,
    req: ResolveRequest = ResolveRequest(),
    current_user: CurrentUser = Depends(require_engineer),
):
    """工程师完成处理后，将工单标记为已解决。"""
    ticket = get_ticket_repository().get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"工单 {ticket_id} 不存在")

    if ticket.status.value != "处理中":
        raise HTTPException(
            status_code=400,
            detail=f"工单当前状态为「{ticket.status.value}」，仅「处理中」状态的工单可标记为已解决",
        )

    if current_user.role != "admin":
        with session_scope() as session:
            record = session.query(TicketRecord).filter(
                TicketRecord.ticket_id == ticket_id
            ).first()
            if record and record.assigned_to != current_user.id:
                raise HTTPException(
                    status_code=403,
                    detail=f"你不是此工单的处理人，无法标记已解决",
                )

    update_kw = {
        "status": "已解决",
        "resolved_at": datetime.now(timezone.utc),
    }
    if req.resolution:
        update_kw["resolution"] = req.resolution

    result = get_ticket_repository().update(ticket_id, **update_kw)
    if not result:
        raise HTTPException(status_code=500, detail="操作失败")

    logger.info(f"工单 {ticket_id} 已被 {current_user.name} 标记为已解决")
    return {"success": True, "message": f"工单 {ticket_id} 已解决", "ticket_id": ticket_id}


# ── 工单操作：关闭归档 ──

@router.post("/ticket/{ticket_id}/close", summary="关闭工单（归档）")
async def close_ticket(
    ticket_id: str,
    current_user: CurrentUser = Depends(require_engineer),
):
    """将已解决的工单关闭归档。"""
    ticket = get_ticket_repository().get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"工单 {ticket_id} 不存在")

    if ticket.status.value != "已解决":
        raise HTTPException(
            status_code=400,
            detail=f"工单当前状态为「{ticket.status.value}」，仅「已解决」状态的工单可归档关闭",
        )

    if current_user.role != "admin":
        with session_scope() as session:
            record = session.query(TicketRecord).filter(
                TicketRecord.ticket_id == ticket_id
            ).first()
            if record and record.assigned_to != current_user.id:
                raise HTTPException(
                    status_code=403,
                    detail=f"你不是此工单的处理人，无法关闭",
                )

    result = get_ticket_repository().update(
        ticket_id,
        status="已关闭",
        closed_at=datetime.now(timezone.utc),
    )
    if not result:
        raise HTTPException(status_code=500, detail="操作失败")

    logger.info(f"工单 {ticket_id} 已被 {current_user.name} 关闭归档")
    return {"success": True, "message": f"工单 {ticket_id} 已关闭归档", "ticket_id": ticket_id}


# ── 工单操作：重新打开 ──

@router.post("/ticket/{ticket_id}/reopen", summary="重新打开工单")
async def reopen_ticket(
    ticket_id: str,
    current_user: CurrentUser = Depends(require_any_role),
):
    """重新打开已解决或已关闭的工单。"""
    ticket = get_ticket_repository().get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"工单 {ticket_id} 不存在")

    if ticket.status.value not in ("已解决", "已关闭"):
        raise HTTPException(
            status_code=400,
            detail=f"工单当前状态为「{ticket.status.value}」，仅「已解决」「已关闭」状态的工单可重新打开",
        )

    if current_user.role != "admin":
        with session_scope() as session:
            record = session.query(TicketRecord).filter(
                TicketRecord.ticket_id == ticket_id
            ).first()
            is_creator = record and record.user_id == current_user.user_id
            is_assignee = record and record.assigned_to == current_user.id
            if not is_creator and not is_assignee:
                raise HTTPException(
                    status_code=403,
                    detail=f"你不是此工单的提交人或处理人，无法重新打开",
                )

    result = get_ticket_repository().update(
        ticket_id,
        status="处理中",
        closed_at=None,
    )
    if not result:
        raise HTTPException(status_code=500, detail="操作失败")

    logger.info(f"工单 {ticket_id} 已被 {current_user.name} 重新打开")
    return {"success": True, "message": f"工单 {ticket_id} 已重新打开", "ticket_id": ticket_id}


# ── 用户反馈确认/转人工 ──

@router.post("/ticket/{ticket_id}/confirm", summary="确认已解决")
async def confirm_ticket_resolved(
    ticket_id: str,
    current_user: CurrentUser = Depends(require_any_role),
):
    """用户确认 AI 的回复已解决问题，关闭工单"""
    ticket = get_ticket_repository().get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"工单 {ticket_id} 不存在")
    get_ticket_repository().update(ticket_id, status="已解决", resolved_at=datetime.now(timezone.utc))
    logger.info(f"工单 {ticket_id} 用户确认已解决")
    return {"success": True, "message": "已确认解决", "ticket_id": ticket_id}


@router.post("/ticket/{ticket_id}/reject", summary="未解决转人工")
async def reject_ticket_escalate(
    ticket_id: str,
    reason: str = "",
    current_user: CurrentUser = Depends(require_any_role),
):
    """用户反馈 AI 未解决问题，转人工处理"""
    ticket = get_ticket_repository().get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"工单 {ticket_id} 不存在")
    get_ticket_repository().update(ticket_id, status="已转人工")
    logger.info(f"工单 {ticket_id} 用户确认未解决，已转人工")
    return {"success": True, "message": "已转人工，请耐心等待", "ticket_id": ticket_id}


# ── 工单列表：我的部门工单 ──

@router.get("/tickets/my", summary="我的部门工单")
async def my_department_tickets(
    current_user: CurrentUser = Depends(require_any_role),
):
    """获取当前用户所在部门的工单列表。"""
    with session_scope() as session:
        query = session.query(TicketRecord)

        if current_user.role == "admin":
            pass
        elif current_user.role in ("engineer", "manager"):
            if current_user.department_id:
                query = query.filter(TicketRecord.department_id == current_user.department_id)
            else:
                query = query.filter(TicketRecord.assigned_to == current_user.id)
        else:
            query = query.filter(TicketRecord.user_id == current_user.user_id)

        records = query.order_by(TicketRecord.created_at.desc()).limit(50).all()

    return [
        {
            "ticket_id": r.ticket_id,
            "user_id": r.user_id,
            "user_name": r.user_name,
            "content": r.content[:100],
            "category": r.category,
            "status": r.status,
            "priority": r.priority,
            "assigned_name": r.assigned_name or "",
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in records
    ]


# ── 提交工单（核心接口）──

@router.post("/ticket", response_model=TicketResponse, summary="提交工单")
async def submit_ticket(
    req: TicketRequest,
    current_user: CurrentUser = Depends(require_any_role),
):
    """提交工单，Agent 自动处理"""
    coordinator = get_coordinator()
    result = await coordinator.process(
        user_input=req.content,
        user_id=current_user.user_id,
        session_id=req.session_id,
        images=req.images or [],
        user_category=req.category or "",
    )

    return TicketResponse(
        success=result.get("success", True),
        ticket_id=result.get("ticket_id", ""),
        category=result.get("category", "其他"),
        response=result.get("response", ""),
        trace_id=result.get("trace_id", ""),
        elapsed_seconds=result.get("elapsed_seconds", 0),
        agent_steps=[
            AgentStep(step=s["step"], elapsed=s.get("elapsed", 0), result=s.get("result", {}))
            for s in result.get("agent_steps", [])
        ],
        auto_resolved=result.get("auto_resolved", False),
        error=result.get("error"),
    )


@router.post("/api/ticket/public", response_model=TicketResponse, summary="公开提交工单（免登录）")
async def submit_ticket_public(req: TicketRequest):
    """免登录提交工单。适合需要快速体验的场景，用 guest 身份提交。"""
    coordinator = get_coordinator()
    user_id = req.session_id or "guest"
    result = await coordinator.process(
        user_input=req.content,
        user_id=user_id,
        session_id=req.session_id or f"public_{uuid.uuid4().hex[:8]}",
        images=req.images or [],
        user_category=req.category or "",
    )

    return TicketResponse(
        success=result.get("success", True),
        ticket_id=result.get("ticket_id", ""),
        category=result.get("category", "其他"),
        response=result.get("response", ""),
        trace_id=result.get("trace_id", ""),
        elapsed_seconds=result.get("elapsed_seconds", 0),
        agent_steps=[
            AgentStep(step=s["step"], elapsed=s.get("elapsed", 0), result=s.get("result", {}))
            for s in result.get("agent_steps", [])
        ],
        auto_resolved=result.get("auto_resolved", False),
        error=result.get("error"),
    )


@router.post("/ticket/stream", summary="流式提交工单 (SSE)")
async def submit_ticket_stream(req: StreamTicketRequest):
    """流式提交工单，通过 SSE 协议实时推送处理进度。"""
    coordinator = get_coordinator()
    stream = SSETicketStream(coordinator)

    return StreamingResponse(
        stream.process(
            user_input=req.content,
            session_id=req.session_id or "default",
            user_id=req.user_id or "",
            images=req.images or [],
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/ticket/{ticket_id}", response_model=TicketInfoResponse, summary="查询工单")
async def get_ticket(
    ticket_id: str,
    current_user: CurrentUser = Depends(require_any_role),
):
    """查询工单当前状态和处理结果"""
    ticket = get_ticket_repository().get(ticket_id)
    if not ticket:
        raise HTTPException(status_code=404, detail=f"工单 {ticket_id} 不存在")

    # 获取 SLA 数据
    sla_deadline = ""
    sla_breached = False
    with session_scope() as session:
        from ticket_agent.database.models import TicketRecord
        record = session.query(TicketRecord).filter(
            TicketRecord.ticket_id == ticket_id
        ).first()
        if record:
            sla_deadline = record.sla_deadline.isoformat() if record.sla_deadline else ""
            sla_breached = record._is_sla_breached()

    return TicketInfoResponse(
        ticket_id=ticket.ticket_id,
        user_id=ticket.user_id,
        content=ticket.content,
        category=ticket.category.value if ticket.category else "",
        status=ticket.status.value if ticket.status else "",
        assignee=ticket.assignee,
        resolution=ticket.resolution if hasattr(ticket, 'resolution') else "",
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        agent_response=ticket.agent_response,
        trace_id=ticket.trace_id,
        sla_deadline=sla_deadline,
        sla_breached=sla_breached,
    )


@router.get("/tickets", response_model=list[TicketInfoResponse], summary="工单列表")
async def list_tickets(
    limit: int = Query(20, description="返回数量"),
    offset: int = Query(0, description="偏移量"),
    current_user: CurrentUser = Depends(require_any_role),
):
    """获取工单列表"""
    tickets = get_ticket_repository().list_all(limit=limit, offset=offset)

    # 批量获取 SLA 数据
    sla_map = {}
    ticket_ids = [t.ticket_id for t in tickets if t.ticket_id]
    if ticket_ids:
        with session_scope() as session:
            from ticket_agent.database.models import TicketRecord
            records = session.query(TicketRecord).filter(
                TicketRecord.ticket_id.in_(ticket_ids)
            ).all()
            for r in records:
                sla_map[r.ticket_id] = {
                    "sla_deadline": r.sla_deadline.isoformat() if r.sla_deadline else "",
                    "sla_breached": r._is_sla_breached(),
                }

    return [
        TicketInfoResponse(
            ticket_id=t.ticket_id,
            user_id=t.user_id,
            content=t.content[:100],
            category=t.category.value if t.category else "",
            status=t.status.value if t.status else "",
            assignee=t.assignee,
            created_at=t.created_at,
            updated_at=t.updated_at,
            agent_response=t.agent_response[:100] if t.agent_response else "",
            trace_id=t.trace_id,
            sla_deadline=sla_map.get(t.ticket_id, {}).get("sla_deadline", ""),
            sla_breached=sla_map.get(t.ticket_id, {}).get("sla_breached", False),
        )
        for t in tickets
    ]


@router.get("/trace/{trace_id}", summary="查看 Agent 执行链路")
async def get_trace(
    trace_id: str,
    current_user: CurrentUser = Depends(require_any_role),
):
    """查看指定 trace_id 的 Agent 完整执行链路"""
    trace_file = os.getenv("AGENT_TRACE_FILE", "traces/agent_runs.jsonl")

    if not os.path.exists(trace_file):
        raise HTTPException(status_code=404, detail=f"Trace 文件不存在")

    with open(trace_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("trace_id") == trace_id:
                return record

    raise HTTPException(status_code=404, detail=f"Trace {trace_id} 未找到")


@router.get("/tickets/export", summary="导出工单 CSV")
async def export_tickets_csv(
    current_user: CurrentUser = Depends(require_any_role),
):
    """导出工单列表为 CSV 文件"""
    import csv
    import io

    from ticket_agent.database import session_scope
    from ticket_agent.database.models import TicketRecord

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["工单号", "提交人", "内容", "分类", "状态", "优先级",
                     "处理人", "创建时间", "解决时间", "SLA截止", "SLA超时"])

    with session_scope() as session:
        records = session.query(TicketRecord).order_by(
            TicketRecord.created_at.desc()
        ).all()

        for r in records:
            sla_breached = r._is_sla_breached()
            writer.writerow([
                r.ticket_id,
                r.user_id,
                r.content,
                r.category,
                r.status,
                r.priority,
                r.assigned_name or "",
                r.created_at.isoformat() if r.created_at else "",
                r.resolved_at.isoformat() if r.resolved_at else "",
                r.sla_deadline.isoformat() if r.sla_deadline else "",
                "是" if sla_breached else "否",
            ])

    from fastapi.responses import StreamingResponse
    output.seek(0)
    filename = f"tickets_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── 批量操作 ──

class BatchActionRequest(BaseModel):
    ticket_ids: list[str]


@router.post("/tickets/batch/close", summary="批量关闭工单")
async def batch_close_tickets(
    req: BatchActionRequest,
    current_user: CurrentUser = Depends(require_engineer),
):
    """批量关闭已解决的工单（仅「已解决」状态的工单会被关闭）"""
    if not req.ticket_ids:
        raise HTTPException(status_code=400, detail="请指定要关闭的工单")
    from datetime import datetime, timezone
    count = get_ticket_repository().batch_update(
        req.ticket_ids, status="已关闭", closed_at=datetime.now(timezone.utc),
    )
    logger.info(f"批量关闭 {count} 个工单 (by {current_user.user_id})")
    return {"success": True, "message": f"已关闭 {count} 个工单", "count": count}


@router.post("/tickets/batch/assign", summary="批量分配工单")
async def batch_assign_tickets(
    req: BatchActionRequest,
    current_user: CurrentUser = Depends(require_engineer),
):
    """批量接单（仅「待处理」状态的工单会被分配）"""
    if not req.ticket_ids:
        raise HTTPException(status_code=400, detail="请指定要接单的工单")
    count = get_ticket_repository().batch_update(
        req.ticket_ids, status="处理中",
        assigned_to=current_user.id, assigned_name=current_user.name,
    )
    logger.info(f"批量接单 {count} 个工单 (by {current_user.user_id})")
    return {"success": True, "message": f"已接单 {count} 个工单", "count": count}


@router.post("/tickets/batch/escalate", summary="批量转人工")
async def batch_escalate_tickets(
    req: BatchActionRequest,
    current_user: CurrentUser = Depends(require_engineer),
):
    """批量转人工处理"""
    if not req.ticket_ids:
        raise HTTPException(status_code=400, detail="请指定要转人工的工单")
    count = get_ticket_repository().batch_update(
        req.ticket_ids, status="已转人工",
    )
    logger.info(f"批量转人工 {count} 个工单 (by {current_user.user_id})")
    return {"success": True, "message": f"已转人工 {count} 个工单", "count": count}
