"""
知识库管理路由

提供知识库文档的 CRUD 接口。
"""
import logging

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel

from ticket_agent.auth import require_any_role, require_manager, CurrentUser
from ticket_agent.knowledge.store import get_knowledge_store
from ticket_agent.knowledge.embedding_pipeline import get_embedding_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="", tags=["知识库管理"])


VALID_CATEGORIES = ["IT", "HR", "财务", "运维"]


class KnowledgeCreateRequest(BaseModel):
    content: str
    category: str
    source: str = "用户上传"


class KnowledgeUpdateRequest(BaseModel):
    content: str | None = None
    category: str | None = None
    source: str | None = None


class KnowledgeDocResponse(BaseModel):
    doc_id: str
    content: str
    category: str
    source: str
    created_at: str
    updated_at: str


@router.get("/knowledge", response_model=list[KnowledgeDocResponse], summary="知识库文档列表")
async def list_knowledge(
    category: str = Query(None, description="按分类过滤: IT/HR/财务/运维"),
    current_user: CurrentUser = Depends(require_any_role),
):
    """获取知识库文档列表，可按分类过滤"""
    docs = get_knowledge_store().list_docs(category)
    return [KnowledgeDocResponse(**d) for d in docs]


@router.get("/knowledge/{doc_id}", response_model=KnowledgeDocResponse, summary="获取知识库文档")
async def get_knowledge_doc(
    doc_id: str,
    current_user: CurrentUser = Depends(require_any_role),
):
    """获取单篇知识库文档"""
    doc = get_knowledge_store().get_doc(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")
    return KnowledgeDocResponse(**doc)


@router.post("/knowledge", response_model=KnowledgeDocResponse, summary="新增知识库文档")
async def create_knowledge_doc(
    req: KnowledgeCreateRequest,
    current_user: CurrentUser = Depends(require_manager),
):
    """新增一篇知识库文档（需要经理/管理员权限）"""
    if req.category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"不支持的知识库分类: {req.category}，可选: {VALID_CATEGORIES}")

    doc = get_knowledge_store().add_doc(content=req.content, category=req.category, source=req.source)
    logger.info(f"知识库新增文档: {doc['doc_id']} [{req.category}]（操作人: {current_user.user_id}）")

    try:
        await get_embedding_pipeline().on_doc_added(doc["doc_id"], doc["content"], doc["category"])
    except Exception as e:
        logger.warning(f"Embedding 同步触发失败（不影响入库）: {e}")

    return KnowledgeDocResponse(**doc)


@router.put("/knowledge/{doc_id}", response_model=KnowledgeDocResponse, summary="更新知识库文档")
async def update_knowledge_doc(
    doc_id: str,
    req: KnowledgeUpdateRequest,
    current_user: CurrentUser = Depends(require_manager),
):
    """更新知识库文档内容/分类/来源（需要经理/管理员权限）"""
    update_kw = {k: v for k, v in req.model_dump().items() if v is not None}
    if not update_kw:
        raise HTTPException(status_code=400, detail="没有需要更新的字段")
    if req.category and req.category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"不支持的知识库分类: {req.category}")

    doc = get_knowledge_store().update_doc(doc_id, **update_kw)
    if not doc:
        raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")
    logger.info(f"知识库更新文档: {doc_id}（操作人: {current_user.user_id}）")

    try:
        await get_embedding_pipeline().on_doc_updated(doc["doc_id"], doc["content"], doc["category"])
    except Exception as e:
        logger.warning(f"Embedding 同步触发失败: {e}")

    return KnowledgeDocResponse(**doc)


@router.delete("/knowledge/{doc_id}", summary="删除知识库文档")
async def delete_knowledge_doc(
    doc_id: str,
    current_user: CurrentUser = Depends(require_manager),
):
    """删除一篇知识库文档（需要经理/管理员权限）"""
    if not get_knowledge_store().delete_doc(doc_id):
        raise HTTPException(status_code=404, detail=f"文档 {doc_id} 不存在")
    logger.info(f"知识库删除文档: {doc_id}（操作人: {current_user.user_id}）")

    try:
        await get_embedding_pipeline().on_doc_deleted(doc_id)
    except Exception as e:
        logger.warning(f"Embedding 删除同步触发失败: {e}")

    return {"success": True, "message": f"文档 {doc_id} 已删除"}
