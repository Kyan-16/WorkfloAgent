"""
认证依赖注入

提供两个 FastAPI 依赖函数：
- get_current_user: 从 JWT 解析当前用户
- require_role: 角色校验（需要用在 get_current_user 之后）
"""
import os
import secrets
import logging
from typing import List, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel

from ticket_agent.database import session_scope
from ticket_agent.database.models import User

logger = logging.getLogger(__name__)

# JWT 配置
_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))
_ALGORITHM = "HS256"

# HTTP Bearer token 提取器
_bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    """当前登录用户信息（从 JWT 解析后的轻量结构）"""
    id: int
    user_id: str
    name: str
    role: str
    department_id: Optional[int] = None
    department_name: str = ""


def create_token(user: User) -> str:
    """签发 JWT token"""
    from datetime import datetime, timedelta, timezone
    expire_hours = int(os.getenv("JWT_EXPIRE_HOURS", "24"))
    expire = datetime.now(timezone.utc) + timedelta(hours=expire_hours)
    payload = {
        "sub": user.user_id,
        "id": user.id,
        "name": user.name,
        "role": user.role,
        "dept_id": user.department_id,
        "exp": expire,
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> CurrentUser:
    """
    从请求头 Authorization: Bearer <token> 解析当前用户。

    Raises:
        HTTPException(401): token 缺失、无效或已过期
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少认证信息，请在请求头添加 Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(credentials.credentials, _SECRET, algorithms=[_ALGORITHM])
        user_id: str = payload.get("sub", "")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token 无效: 缺少用户标识")
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token 无效或已过期: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 从数据库查询确认用户仍存在且活跃
    with session_scope() as session:
        user = session.query(User).filter(User.user_id == user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="用户不存在或已被删除")
        if not user.is_active:
            raise HTTPException(status_code=401, detail="账户已被禁用")

        dept_name = ""
        if user.department_id:
            from ticket_agent.database.models import Department
            dept = session.query(Department).filter(Department.id == user.department_id).first()
            if dept:
                dept_name = dept.name

        return CurrentUser(
            id=user.id,
            user_id=user.user_id,
            name=user.name,
            role=user.role,
            department_id=user.department_id,
            department_name=dept_name,
        )


class RoleChecker:
    """角色校验器——可用作 Depends"""

    def __init__(self, *allowed_roles: str):
        self.allowed_roles = allowed_roles

    async def __call__(self, current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足（需要角色: {', '.join(self.allowed_roles)}，当前角色: {current_user.role}）",
            )
        return current_user


# 快捷用法
require_admin = RoleChecker("admin")
require_manager = RoleChecker("manager", "admin")
require_engineer = RoleChecker("engineer", "manager", "admin")
require_any_role = RoleChecker("employee", "engineer", "manager", "admin")
