"""认证路由 —— 登录 / 注册 / 当前用户"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from passlib.hash import bcrypt

from ticket_agent.database import session_scope
from ticket_agent.database.models import User
from ticket_agent.auth.schemas import LoginRequest, TokenResponse, RegisterRequest, ChangePasswordRequest
from ticket_agent.auth.dependencies import (
    get_current_user, create_token, CurrentUser,
    require_admin,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login", response_model=TokenResponse, summary="用户登录")
async def login(req: LoginRequest):
    """
    用户登录，返回 JWT token。

    默认密码: 123456（种子用户）
    """
    with session_scope() as session:
        user = session.query(User).filter(User.user_id == req.user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="用户不存在")

        if not user.hashed_password:
            raise HTTPException(status_code=401, detail="该用户未设置密码，请联系管理员")

        if not bcrypt.verify(req.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="密码错误")

        if not user.is_active:
            raise HTTPException(status_code=401, detail="账户已被禁用")

        token = create_token(user)

        dept_name = ""
        if user.department_id:
            from ticket_agent.database.models import Department
            dept = session.query(Department).filter(Department.id == user.department_id).first()
            if dept:
                dept_name = dept.name

        return TokenResponse(
            access_token=token,
            user_id=user.user_id,
            name=user.name,
            role=user.role,
            department_id=user.department_id,
            department_name=dept_name,
        )


@router.get("/me", response_model=TokenResponse, summary="当前用户信息")
async def me(current_user: CurrentUser = Depends(get_current_user)):
    """获取当前登录用户的信息"""
    return TokenResponse(
        access_token="",  # 不返回 token
        user_id=current_user.user_id,
        name=current_user.name,
        role=current_user.role,
        department_id=current_user.department_id,
        department_name=current_user.department_name,
    )


@router.post("/register", summary="注册新用户")
async def register(
    req: RegisterRequest,
    current_user: CurrentUser = Depends(require_admin),
):
    """注册新用户（需要管理员权限）"""
    with session_scope() as session:
        existing = session.query(User).filter(User.user_id == req.user_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="用户已存在")

        user = User(
            user_id=req.user_id,
            name=req.name,
            role=req.role,
            department_id=req.department_id,
            email=req.email,
            hashed_password=bcrypt.hash(req.password),
        )
        session.add(user)

    return {"success": True, "message": f"用户 {req.user_id} 注册成功"}


@router.post("/change-password", summary="修改密码")
async def change_password(
    req: ChangePasswordRequest,
    current_user: CurrentUser = Depends(get_current_user),
):
    """修改当前登录用户的密码。需要提供旧密码验证身份。"""
    with session_scope() as session:
        user = session.query(User).filter(User.id == current_user.id).first()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        if not bcrypt.verify(req.old_password, user.hashed_password):
            raise HTTPException(status_code=400, detail="旧密码错误")
        user.hashed_password = bcrypt.hash(req.new_password)
    return {"success": True, "message": "密码修改成功"}
