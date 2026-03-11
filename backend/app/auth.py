"""
Xác thực: hash mật khẩu, tạo/giải mã JWT, dependency lấy user hiện tại.
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings
from app.repositories import user_repository

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=settings.jwt_expire_minutes)
    to_encode["exp"] = expire
    return jwt.encode(
        to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str) -> Optional[dict]:
    try:
        payload = jwt.decode(
            token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
        )
        return payload
    except JWTError:
        return None


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[dict]:
    """
    Lấy user hiện tại nếu có Bearer token hợp lệ.
    Không bắt buộc đăng nhập: trả về None nếu không có token hoặc token sai.
    """
    if not credentials or not credentials.credentials:
        return None
    payload = decode_access_token(credentials.credentials)
    if not payload or "sub" not in payload:
        return None
    user_id = payload["sub"]
    user = await user_repository.get_user_by_id(user_id)
    if not user:
        return None
    return user


async def get_current_user(
    user: Optional[dict] = Depends(get_current_user_optional),
) -> dict:
    """
    Bắt buộc đăng nhập. Dùng cho các route cần auth.
    """
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Chưa đăng nhập hoặc token không hợp lệ",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def user_to_response(doc: dict) -> dict:
    """Chuyển document user từ DB sang dạng trả về API (có id, không có hashed_password)."""
    return {
        "id": str(doc["_id"]),
        "email": doc["email"],
        "username": doc["username"],
        "created_at": doc.get("created_at"),
    }
