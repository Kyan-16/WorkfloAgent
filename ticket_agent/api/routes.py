"""
API 路由集合

包含所有子路由模块的聚合，以及全局 coordinator 的访问函数。

向后兼容：外部模块通过 from ticket_agent.api.routes import get_coordinator
仍可正常工作。
"""
from ticket_agent.api.deps import get_coordinator, set_coordinator
from ticket_agent.api.routes_ticket import router as ticket_router
from ticket_agent.api.routes_knowledge import router as knowledge_router
from ticket_agent.api.routes_feedback import router as feedback_router
from ticket_agent.api.routes_model import router as model_router
from ticket_agent.api.routes_misc import router as misc_router

from fastapi import APIRouter

router = APIRouter()
router.include_router(ticket_router)
router.include_router(knowledge_router)
router.include_router(feedback_router)
router.include_router(model_router)
router.include_router(misc_router)

__all__ = ["router", "get_coordinator", "set_coordinator"]
