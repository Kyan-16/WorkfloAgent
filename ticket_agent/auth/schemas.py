"""认证模块 Pydantic 模型"""
from pydantic import BaseModel
from typing import Optional


class LoginRequest(BaseModel):
    user_id: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    name: str
    role: str
    department_id: Optional[int] = None
    department_name: str = ""


class RegisterRequest(BaseModel):
    user_id: str
    password: str
    name: str
    role: str = "employee"
    department_id: Optional[int] = None
    email: str = ""


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str
