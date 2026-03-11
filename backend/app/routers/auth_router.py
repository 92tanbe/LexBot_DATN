"""
API đăng ký và đăng nhập.
"""
from fastapi import APIRouter, Depends, HTTPException, status

from app.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    user_to_response,
    verify_password,
)
from app.models.user import UserCreate, UserLogin, UserResponse
from app.repositories import user_repository

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse)
async def register(data: UserCreate):
    """
    Đăng ký tài khoản mới.
    Email và username không trùng với tài khoản đã có.
    """
    existing = await user_repository.get_user_by_email(data.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email này đã được sử dụng",
        )
    hashed = hash_password(data.password)
    doc = await user_repository.create_user(
        email=data.email,
        username=data.username,
        hashed_password=hashed,
    )
    return UserResponse(
        id=str(doc["_id"]),
        email=doc["email"],
        username=doc["username"],
        created_at=doc.get("created_at"),
    )


@router.post("/login")
async def login(data: UserLogin):
    """
    Đăng nhập bằng email và mật khẩu.
    Trả về access_token và thông tin user.
    """
    user = await user_repository.get_user_by_email(data.email)
    if not user or not verify_password(data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email hoặc mật khẩu không đúng",
        )
    token = create_access_token(data={"sub": str(user["_id"])})
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_to_response(user),
    }


@router.get("/me", response_model=UserResponse)
async def me(user: dict = Depends(get_current_user)):
    """Lấy thông tin tài khoản hiện tại (cần gửi kèm Bearer token)."""
    return user_to_response(user)
