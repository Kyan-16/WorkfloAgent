"""
杂项路由：统计、上传、分类

提供系统统计总览、文件上传、工单分类列表等接口。
"""
import logging
import os
import uuid

from fastapi import APIRouter, HTTPException, Query, Depends, UploadFile, File as FastAPIFile

from ticket_agent.api.schemas import UploadResponse
from ticket_agent.api.deps import get_coordinator
from ticket_agent.auth import require_any_role, CurrentUser
from ticket_agent.repository import get_ticket_repository
from ticket_agent.feedback.store import get_feedback_store
from ticket_agent.evolution.reviewer import get_review_store
from ticket_agent.evolution.accuracy_tracker import get_accuracy_store
from ticket_agent.evolution.knowledge_gap import get_gap_store
from ticket_agent.memory.pattern_extractor import get_pattern_store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="", tags=["系统"])


@router.get("/stats", summary="系统统计总览")
async def get_system_stats(
    current_user: CurrentUser = Depends(require_any_role),
):
    """获取系统运行统计总览"""
    tickets = get_ticket_repository().list_all(limit=1000)
    total = len(tickets)
    by_category = {}
    by_status = {}
    auto_resolved = 0
    escalated = 0
    for t in tickets:
        cat = t.category.value if t.category else "其他"
        by_category[cat] = by_category.get(cat, 0) + 1
        st = t.status.value if t.status else "未知"
        by_status[st] = by_status.get(st, 0) + 1
        if st == "已转人工":
            escalated += 1
        elif st == "已解决":
            auto_resolved += 1

    patterns = get_pattern_store().count
    feedback_stats = get_feedback_store().get_stats()
    review_stats = get_review_store().get_stats()
    accuracy_stats = get_accuracy_store().get_stats()
    gap_stats = get_gap_store().get_stats()

    return {
        "tickets": {
            "total": total,
            "by_category": by_category,
            "by_status": by_status,
            "auto_resolved": auto_resolved,
            "escalated": escalated,
            "auto_resolve_rate": round(auto_resolved / total, 2) if total > 0 else 0,
        },
        "patterns": {"total": patterns},
        "feedback": feedback_stats,
        "evolution": {
            "reviews": review_stats,
            "accuracy": accuracy_stats.get("_overall", {}),
            "knowledge_gaps": gap_stats,
        },
    }


@router.post("/upload", response_model=UploadResponse, summary="上传文件（图片）")
async def upload_file(file: UploadFile = FastAPIFile(...)):
    """上传图片/文件，返回可访问的 URL。"""
    ext = os.path.splitext(file.filename or "file")[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {ext}，允许: jpg/jpeg/png/gif/bmp/webp",
        )

    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="文件过大，最大允许 20MB")

    safe_name = f"{uuid.uuid4().hex}{ext}"
    save_dir = os.path.join(os.getcwd(), "uploads")
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, safe_name)

    with open(save_path, "wb") as f:
        f.write(content)

    url = f"/uploads/{safe_name}"
    logger.info(f"文件已上传: {url} ({len(content)} bytes)")

    return UploadResponse(
        url=url,
        filename=file.filename or safe_name,
        size=len(content),
        content_type=file.content_type or "application/octet-stream",
    )


@router.get("/categories", summary="获取工单分类列表")
async def list_categories():
    """获取所有支持的工单分类（公开接口，无需登录）"""
    return {
        "categories": [
            {"name": "IT", "description": "网络/账号/软件/硬件故障"},
            {"name": "HR", "description": "请假/薪酬/招聘/员工关系"},
            {"name": "财务", "description": "报销/发票/预算/合同"},
            {"name": "运维", "description": "告警/部署/数据库/服务器"},
            {"name": "其他", "description": "不属于以上分类"},
        ]
    }
