"""认证模块 —— JWT 登录 + 角色鉴权"""
from ticket_agent.auth.schemas import LoginRequest, TokenResponse, RegisterRequest
from ticket_agent.auth.dependencies import (
    get_current_user, create_token, CurrentUser, RoleChecker,
    require_admin, require_manager, require_engineer, require_any_role,
)
from ticket_agent.auth.routes import router

__all__ = [
    "LoginRequest", "TokenResponse", "RegisterRequest",
    "get_current_user", "require_role",
    "router",
]
