"""
Schema cho tin nhắn và lịch sử chat (theo user_id).
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Message(BaseModel):
    """Một tin nhắn trong hội thoại."""

    role: str  # "user" | "assistant" | "system"
    content: str


class MessageWithTime(Message):
    """Tin nhắn kèm thời gian (khi lưu DB)."""

    created_at: Optional[datetime] = None


class ChatRequest(BaseModel):
    """Payload gửi từ client khi gọi /chat."""

    messages: List[Message]
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    """Phản hồi từ endpoint /chat."""

    reply: str
    session_id: Optional[str] = None


class ChatHistoryItem(BaseModel):
    """Một đoạn hội thoại (session) trong lịch sử."""

    session_id: str
    messages: List[MessageWithTime]
    updated_at: Optional[datetime] = None


class ChatHistoryListResponse(BaseModel):
    """Danh sách các session chat của user (tóm tắt)."""

    sessions: List[dict]  # [{ "session_id", "updated_at", "message_count" }]


class ChatSessionDetailResponse(BaseModel):
    """Chi tiết một session: toàn bộ messages."""

    session_id: str
    messages: List[MessageWithTime]
    updated_at: Optional[datetime] = None
