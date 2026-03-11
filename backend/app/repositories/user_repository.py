"""
Truy cập collection users trong MongoDB.
"""
from datetime import datetime
from typing import Optional

from app.database import get_database
from app.models.user import UserInDB


COLLECTION_NAME = "users"


async def get_user_by_email(email: str) -> Optional[dict]:
    """Lấy user theo email."""
    db = get_database()
    doc = await db[COLLECTION_NAME].find_one({"email": email.lower()})
    return doc


async def get_user_by_id(user_id: str) -> Optional[dict]:
    """Lấy user theo _id (ObjectId string)."""
    from bson import ObjectId

    db = get_database()
    try:
        doc = await db[COLLECTION_NAME].find_one({"_id": ObjectId(user_id)})
        return doc
    except Exception:
        return None


async def create_user(email: str, username: str, hashed_password: str) -> dict:
    """
    Tạo user mới. Trả về document đã chèn (có _id).
    Email lưu dạng chữ thường.
    """
    db = get_database()
    now = datetime.utcnow()
    doc = {
        "email": email.lower(),
        "username": username.strip(),
        "hashed_password": hashed_password,
        "created_at": now,
    }
    result = await db[COLLECTION_NAME].insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc
