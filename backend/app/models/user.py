"""
Schema và logic liên quan tài khoản người dùng.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    """Payload đăng ký tài khoản."""

    email: EmailStr
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)


class UserLogin(BaseModel):
    """Payload đăng nhập (email + mật khẩu)."""

    email: EmailStr
    password: str


class UserResponse(BaseModel):
    """Thông tin user trả về (không có mật khẩu)."""

    id: str
    email: str
    username: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserInDB(BaseModel):
    """User lưu trong DB (có hashed_password)."""

    email: str
    username: str
    hashed_password: str
    created_at: Optional[datetime] = None
