"""
Truy cập collection chat_histories: lưu/lấy lịch sử chat theo user_id.
"""
from datetime import datetime
from typing import List, Optional

from bson import ObjectId

from app.database import get_database

COLLECTION_NAME = "chat_histories"


def _serialize_doc(doc: dict) -> dict:
    """Chuyển _id sang string cho JSON."""
    if doc and "_id" in doc:
        doc = {**doc, "_id": str(doc["_id"])}
    return doc


async def get_or_create_session(user_id: str, session_id: Optional[str] = None) -> str:
    """
    Lấy session_id đang dùng hoặc tạo session mới.
    Trả về session_id (string).
    """
    if session_id:
        return session_id
    return str(ObjectId())


async def append_messages(
    user_id: str,
    session_id: str,
    new_messages: List[dict],
) -> None:
    """
    Thêm các tin nhắn vào session của user.
    Mỗi message cần có: role, content; sẽ thêm created_at.
    """
    db = get_database()
    now = datetime.utcnow()
    for m in new_messages:
        m["created_at"] = now

    await db[COLLECTION_NAME].update_one(
        {"user_id": user_id, "session_id": session_id},
        {
            "$set": {"updated_at": now, "user_id": user_id, "session_id": session_id},
            "$push": {"messages": {"$each": new_messages}},
        },
        upsert=True,
    )


async def get_session_messages(user_id: str, session_id: str) -> List[dict]:
    """Lấy toàn bộ messages của một session."""
    db = get_database()
    doc = await db[COLLECTION_NAME].find_one(
        {"user_id": user_id, "session_id": session_id}
    )
    if not doc or "messages" not in doc:
        return []
    return doc.get("messages", [])


async def list_sessions(user_id: str, limit: int = 50) -> List[dict]:
    """
    Liệt kê các session của user (session_id, updated_at, message_count).
    Sắp xếp theo updated_at giảm dần.
    """
    db = get_database()
    cursor = db[COLLECTION_NAME].aggregate(
        [
            {"$match": {"user_id": user_id}},
            {"$sort": {"updated_at": -1}},
            {"$limit": limit},
            {
                "$project": {
                    "session_id": 1,
                    "updated_at": 1,
                    "message_count": {"$size": {"$ifNull": ["$messages", []]}},
                }
            },
        ]
    )
    sessions = []
    async for doc in cursor:
        sessions.append(_serialize_doc(doc))
    return sessions


async def get_session_detail(user_id: str, session_id: str) -> Optional[dict]:
    """Lấy chi tiết một session (messages + updated_at)."""
    db = get_database()
    doc = await db[COLLECTION_NAME].find_one(
        {"user_id": user_id, "session_id": session_id}
    )
    if not doc:
        return None
    return _serialize_doc(doc)
