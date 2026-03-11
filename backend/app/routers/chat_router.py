"""
API chat: gửi tin nhắn, lưu lịch sử theo user_id, xem lịch sử.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.models.chat import ChatRequest, ChatResponse
from app.repositories import chat_repository

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    user: dict = Depends(get_current_user),
):
    """
    Gửi tin nhắn tới chatbot. Yêu cầu đăng nhập (Bearer token).
    Lưu lịch sử (messages + reply) vào MongoDB theo user_id và session_id.
    """
    user_id = str(user["_id"])
    session_id = await chat_repository.get_or_create_session(
        user_id, request.session_id
    )

    # Lấy tin nhắn user mới nhất để tạo reply mẫu
    user_message = ""
    for msg in reversed(request.messages):
        if msg.role == "user":
            user_message = msg.content
            break

    # TODO: Thay bằng gọi mô hình AI thật
    reply = (
        f"Bạn vừa nói: '{user_message}'. "
        f"Backend đã lưu lịch sử theo tài khoản của bạn."
    )

    # Lưu vào DB: tin nhắn user (mới nhất hoặc cả list) + reply assistant
    to_save: List[dict] = []
    for m in request.messages:
        to_save.append({"role": m.role, "content": m.content})
    to_save.append({"role": "assistant", "content": reply})
    await chat_repository.append_messages(user_id, session_id, to_save)

    return ChatResponse(reply=reply, session_id=session_id)


@router.get("/history")
async def list_chat_history(
    user: dict = Depends(get_current_user),
    limit: int = 50,
):
    """
    Liệt kê các phiên chat (session) của user, sắp xếp theo thời gian cập nhật.
    """
    user_id = str(user["_id"])
    sessions = await chat_repository.list_sessions(user_id, limit=limit)
    return {"sessions": sessions}


@router.get("/history/{session_id}")
async def get_chat_session(
    session_id: str,
    user: dict = Depends(get_current_user),
):
    """Lấy toàn bộ tin nhắn của một phiên chat theo session_id."""
    user_id = str(user["_id"])
    doc = await chat_repository.get_session_detail(user_id, session_id)
    if not doc:
        return {"session_id": session_id, "messages": []}
    return {
        "session_id": doc["session_id"],
        "messages": doc.get("messages", []),
        "updated_at": doc.get("updated_at"),
    }
