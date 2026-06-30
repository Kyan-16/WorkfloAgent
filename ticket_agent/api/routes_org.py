"""
组织架构与工作流 API

提供用户、部门队列、接单、审批等角色化接口。
所有接口需要登录认证，并根据操作类型校验角色权限。
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends, Body
from pydantic import BaseModel
from pydantic import BaseModel

from ticket_agent.database import session_scope
from ticket_agent.database.models import User, Department, TicketRecord, Approval
from ticket_agent.auth import (
    get_current_user, require_any_role, require_engineer, require_manager,
    require_admin, CurrentUser,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/org", tags=["组织架构与工作流"])


# ── 请求模型 ──

class TicketActionRequest(BaseModel):
    """接单/完成/分配等操作的请求体"""
    ticket_id: str


class ResolveRequest(BaseModel):
    """完成工单的请求体"""
    ticket_id: str
    resolution: str = ""


class AssignRequest(BaseModel):
    """分配工单的请求体"""
    ticket_id: str
    assignee_id: int


# ── 用户（admin / manager 可查看所有）──

@router.get("/users", summary="用户列表")
async def list_users(
    department_id: int = Query(None),
    current_user: CurrentUser = Depends(require_manager),
):
    """查询用户列表（需要经理/管理员权限）"""
    with session_scope() as session:
        q = session.query(User)
        if department_id:
            q = q.filter(User.department_id == department_id)
        users = q.order_by(User.department_id, User.role).all()
        return [u.to_dict() for u in users]


@router.get("/users/me", summary="当前用户信息")
async def get_current_user_info(
    current_user: CurrentUser = Depends(require_any_role),
):
    """获取当前登录用户的信息（从 JWT token 解析）"""
    with session_scope() as session:
        user = session.query(User).filter(User.user_id == current_user.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        return user.to_dict()


@router.get("/users/{user_id}", summary="用户详情")
async def get_user(
    user_id: str,
    current_user: CurrentUser = Depends(require_manager),
):
    """查询指定用户详情（需要经理/管理员权限）"""
    with session_scope() as session:
        user = session.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail=f"用户 {user_id} 不存在")
        return user.to_dict()


# ── 部门（登录即可查看）──

@router.get("/departments", summary="部门列表")
async def list_departments(
    current_user: CurrentUser = Depends(require_any_role),
):
    """获取部门列表及人员/工单统计"""
    with session_scope() as session:
        depts = session.query(Department).all()
        result = []
        for d in depts:
            user_count = session.query(User).filter(User.department_id == d.id).count()
            pending_count = session.query(TicketRecord).filter(
                TicketRecord.department_id == d.id,
                TicketRecord.status.in_(["待处理", "处理中", "待审批"]),
            ).count()
            result.append({
                "id": d.id,
                "name": d.name,
                "description": d.description,
                "user_count": user_count,
                "pending_tickets": pending_count,
            })
        return result


# ── 工单队列（工程师/经理/管理员可见）──

@router.get("/queue/department/{dept_id}", summary="部门工单队列")
async def department_queue(
    dept_id: int,
    status: str = Query(None, description="过滤状态"),
    limit: int = Query(20),
    current_user: CurrentUser = Depends(require_engineer),
):
    """查询指定部门的工单队列（需要工程师/经理/管理员权限）"""
    with session_scope() as session:
        q = session.query(TicketRecord).filter(TicketRecord.department_id == dept_id)
        if status:
            q = q.filter(TicketRecord.status == status)
        tickets = q.order_by(TicketRecord.created_at.desc()).limit(limit).all()
        return [t.to_dict() for t in tickets]


@router.get("/queue/my", summary="我的待办工单")
async def my_tickets(
    status: str = Query(None),
    current_user: CurrentUser = Depends(require_any_role),
):
    """查询分配给当前用户的工单（根据角色自动区分视角）"""
    with session_scope() as session:
        user = session.query(User).filter(User.user_id == current_user.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        if user.role in ("engineer", "manager", "admin"):
            q = session.query(TicketRecord).filter(
                TicketRecord.assigned_to == user.id
            )
        else:
            q = session.query(TicketRecord).filter(
                TicketRecord.user_id == current_user.user_id
            )

        if status:
            q = q.filter(TicketRecord.status == status)
        tickets = q.order_by(TicketRecord.created_at.desc()).limit(20).all()
        return [t.to_dict() for t in tickets]


@router.post("/queue/assign/{ticket_id}", summary="分配工单")
async def assign_ticket(
    ticket_id: str,
    assignee_id: int = Body(...),
    current_user: CurrentUser = Depends(require_manager),
):
    """将工单分配给指定用户（需要经理/管理员权限）"""
    with session_scope() as session:
        ticket = session.query(TicketRecord).filter(
            TicketRecord.ticket_id == ticket_id
        ).first()
        if not ticket:
            raise HTTPException(status_code=404, detail="工单不存在")

        assignee = session.query(User).filter(User.id == assignee_id).first()
        if not assignee:
            raise HTTPException(status_code=404, detail="用户不存在")

        ticket.assigned_to = assignee.id
        ticket.assigned_name = assignee.name
        if ticket.status == "待处理":
            ticket.status = "处理中"

        logger.info(f"工单 {ticket_id} 由 {current_user.user_id} 分配给 {assignee.name}")
        return {"success": True, "message": f"工单已分配给 {assignee.name}"}


@router.post("/queue/accept/{ticket_id}", summary="接单")
async def accept_ticket(
    ticket_id: str,
    current_user: CurrentUser = Depends(require_engineer),
):
    """工程师接单（需要工程师/经理/管理员权限）"""
    with session_scope() as session:
        ticket = session.query(TicketRecord).filter(
            TicketRecord.ticket_id == ticket_id
        ).first()
        if not ticket:
            raise HTTPException(status_code=404, detail="工单不存在")

        user = session.query(User).filter(User.user_id == current_user.user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        # 部门边界校验：普通工程师只能接本部门工单
        if user.role == "engineer" and user.department_id and ticket.department_id:
            if user.department_id != ticket.department_id:
                raise HTTPException(status_code=403, detail="只能接本部门的工单")

        ticket.assigned_to = user.id
        ticket.assigned_name = user.name
        ticket.status = "处理中"
        logger.info(f"工单 {ticket_id} 由 {user.name} 接单")
        return {"success": True, "message": f"{user.name} 已接单"}


@router.post("/queue/resolve/{ticket_id}", summary="完成工单")
async def resolve_ticket(
    ticket_id: str,
    resolution: str = "",
    current_user: CurrentUser = Depends(require_engineer),
):
    """工程师标记工单为已解决（需要工程师/经理/管理员权限）"""
    with session_scope() as session:
        ticket = session.query(TicketRecord).filter(
            TicketRecord.ticket_id == ticket_id
        ).first()
        if not ticket:
            raise HTTPException(status_code=404, detail="工单不存在")

        user = session.query(User).filter(User.user_id == current_user.user_id).first()
        if user and user.role == "engineer" and user.department_id and ticket.department_id:
            if user.department_id != ticket.department_id:
                raise HTTPException(status_code=403, detail="只能操作本部门的工单")

        ticket.status = "已解决"
        ticket.resolved_at = datetime.utcnow()
        if resolution:
            ticket.agent_response = (ticket.agent_response or "") + f"\n\n[处理结果] {resolution}"
        logger.info(f"工单 {ticket_id} 由 {current_user.user_id} 标记为已解决")
        return {"success": True, "message": "工单已完成"}


# ── 审批（经理/管理员）──

@router.get("/approvals/pending", summary="待审批列表")
async def pending_approvals(
    approver_id: int = Query(None),
    current_user: CurrentUser = Depends(require_manager),
):
    """查询待审批的工单列表（需要经理/管理员权限）"""
    with session_scope() as session:
        q = session.query(TicketRecord).filter(
            TicketRecord.needs_approval == True,
            TicketRecord.approval_status == "pending",
        )
        if approver_id:
            q = q.join(Approval, TicketRecord.ticket_id == Approval.ticket_id,
                       isouter=True).filter(
                Approval.approver_id == approver_id,
                Approval.status == "pending",
            )
        tickets = q.order_by(TicketRecord.created_at.desc()).all()
        return [t.to_dict() for t in tickets]


@router.get("/approvals/history", summary="审批记录")
async def approval_history(
    ticket_id: str = None,
    current_user: CurrentUser = Depends(require_manager),
):
    """查询审批记录（需要经理/管理员权限）"""
    with session_scope() as session:
        q = session.query(Approval)
        if ticket_id:
            q = q.filter(Approval.ticket_id == ticket_id)
        records = q.order_by(Approval.created_at.desc()).limit(50).all()
        return [r.to_dict() for r in records]


class ApprovalRequest(BaseModel):
    ticket_id: str
    action: str  # approve / reject
    comment: str = ""


@router.post("/approvals/process", summary="处理审批")
async def process_approval(
    req: ApprovalRequest,
    current_user: CurrentUser = Depends(require_manager),
):
    """审批或驳回工单（需要经理/管理员权限）"""
    with session_scope() as session:
        ticket = session.query(TicketRecord).filter(
            TicketRecord.ticket_id == req.ticket_id
        ).first()
        if not ticket:
            raise HTTPException(status_code=404, detail="工单不存在")

        approver = session.query(User).filter(User.user_id == current_user.user_id).first()
        if not approver:
            raise HTTPException(status_code=404, detail="审批人不存在")

        new_status = "approved" if req.action == "approve" else "rejected"
        ticket.approval_status = new_status

        if req.action == "approve":
            ticket.status = "已解决"
        else:
            ticket.status = "已关闭"

        approval = Approval(
            ticket_id=req.ticket_id,
            approver_id=approver.id,
            approver_name=approver.name,
            status=new_status,
            comment=req.comment,
        )
        session.add(approval)

        logger.info(f"工单 {req.ticket_id} 由 {current_user.user_id} {'批准' if req.action == 'approve' else '驳回'}")
        return {
            "success": True,
            "message": f"工单已{'批准' if req.action == 'approve' else '驳回'}",
            "approval_status": new_status,
        }


# ── 统计（登录即可查看）──

@router.get("/stats/dashboard", summary="工作台概览")
async def dashboard_stats(
    current_user: CurrentUser = Depends(require_any_role),
):
    """返回工单系统的统计概览数据"""
    with session_scope() as session:
        total = session.query(TicketRecord).count()
        pending = session.query(TicketRecord).filter(
            TicketRecord.status.in_(["待处理", "处理中"])
        ).count()
        awaiting_approval = session.query(TicketRecord).filter(
            TicketRecord.needs_approval == True,
            TicketRecord.approval_status == "pending",
        ).count()
        resolved = session.query(TicketRecord).filter(
            TicketRecord.status == "已解决"
        ).count()

        dept_stats = []
        for dept in session.query(Department).all():
            cnt = session.query(TicketRecord).filter(
                TicketRecord.department_id == dept.id,
                TicketRecord.status.in_(["待处理", "处理中", "待审批"]),
            ).count()
            dept_stats.append({"name": dept.name, "pending": cnt})

        return {
            "total_tickets": total,
            "pending": pending,
            "awaiting_approval": awaiting_approval,
            "resolved": resolved,
            "departments": dept_stats,
        }
