import logging
import os
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.core.security import decode_token
from app.db.mongodb import chats_collection
from app.models.chat import (
    ChatHistoryDetail,
    ChatHistoryItem,
    ChatHistoryListResponse,
    ChatQueryRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)
oauth2_required = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=True)


def _resolve_chatbot_rag_url(raw: str) -> str:
    """Chuẩn hóa CHATBOT_SERVICE_URL và nối path /rag/query khi chỉ có base URL.

    - Tự thêm https:// nếu env thiếu scheme (hay gặp trên dashboard: chỉ dán hostname).
    """
    value = (raw or "").strip()
    if not value:
        return "http://127.0.0.1:8001/rag/query"
    lowered = value.lower()
    if not lowered.startswith(("http://", "https://")):
        stub = value.lstrip("/")
        if "localhost" in stub.lower() or "127.0.0.1" in stub:
            value = f"http://{stub}"
        else:
            value = f"https://{stub}"

    base = value.rstrip("/")
    path = (urlparse(base).path or "").rstrip("/")
    if not path:
        return f"{base}/rag/query"
    if path.endswith("/rag"):
        return f"{base}/query"
    if path.endswith("/rag/query"):
        return base
    return base


# Local: mặc định chatbot local. Production: CHATBOT_SERVICE_URL = base hoặc full .../rag/query
CHATBOT_URL = _resolve_chatbot_rag_url(
    os.getenv("CHATBOT_SERVICE_URL", "http://127.0.0.1:8001/rag/query")
)
# Railway/host free-tier cold start có thể >60s; kết nối TLS + chờ POST /rag/query cần timeout cao hơn.
CHATBOT_TIMEOUT = float(os.getenv("CHATBOT_TIMEOUT_SECONDS", "120"))
CHATBOT_CONNECT_TIMEOUT = float(
    os.getenv("CHATBOT_CONNECT_TIMEOUT_SECONDS", "45")
)


def _preview_from_response(response_data: dict[str, Any]) -> str:
    text = str(response_data.get("final_answer") or "").strip()
    if len(text) > 280:
        return text[:277] + "..."
    return text


def _doc_created_at(doc: dict[str, Any]) -> datetime:
    ts = doc.get("timestamp") or doc.get("created_at")
    if isinstance(ts, datetime):
        return ts
    return datetime.utcnow()


def _parse_object_id(chat_id: str) -> ObjectId:
    try:
        return ObjectId(chat_id)
    except InvalidId as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="ID lịch sử không hợp lệ.",
        ) from exc


async def require_user_id(token: str = Depends(oauth2_required)) -> str:
    """JWT bắt buộc — dùng cho GET lịch sử."""
    payload = decode_token(token)
    uid = payload.get("sub")
    if not uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token không chứa định danh người dùng.",
        )
    return str(uid)


async def save_chat_to_db(
    user_id: str,
    question: str,
    response_data: dict[str, Any],
    *,
    query_mode: str,
    chat_mode: str | None,
    conversation_id: str | None,
) -> None:
    try:
        chat_document = {
            "user_id": user_id,
            "question": question,
            "response": response_data,
            "timestamp": datetime.utcnow(),
            "query_mode": query_mode,
            "chat_mode": chat_mode,
            "conversation_id": conversation_id,
        }
        await chats_collection.insert_one(chat_document)
    except Exception as e:
        logger.warning("Lưu chat vào MongoDB thất bại: %s", e)


def _mongo_doc_to_list_item(doc: dict[str, Any]) -> ChatHistoryItem:
    resp = doc.get("response") or {}
    if not isinstance(resp, dict):
        resp = {}
    return ChatHistoryItem(
        id=str(doc["_id"]),
        user_id=str(doc.get("user_id", "")),
        question=str(doc.get("question", "")),
        preview_answer=_preview_from_response(resp),
        query_mode=doc.get("query_mode") or "fast",
        chat_mode=doc.get("chat_mode"),
        conversation_id=doc.get("conversation_id"),
        created_at=_doc_created_at(doc),
    )


def _mongo_doc_to_detail(doc: dict[str, Any]) -> ChatHistoryDetail:
    resp = doc.get("response") or {}
    if not isinstance(resp, dict):
        resp = {}
    return ChatHistoryDetail(
        id=str(doc["_id"]),
        user_id=str(doc.get("user_id", "")),
        question=str(doc.get("question", "")),
        query_mode=doc.get("query_mode") or "fast",
        chat_mode=doc.get("chat_mode"),
        conversation_id=doc.get("conversation_id"),
        created_at=_doc_created_at(doc),
        response=resp,
    )


@router.post("/query")
async def chat_query(
    request: ChatQueryRequest,
    background_tasks: BackgroundTasks,
    token: str = Depends(oauth2_scheme),
):
    """
    Forward the chat query from the frontend directly to the RAG Chatbot Microservice.
    """
    user_id = "guest"
    if token:
        try:
            payload = decode_token(token)
            user_id = payload.get("sub", "guest")
        except Exception:
            pass

    connect_cap = min(CHATBOT_CONNECT_TIMEOUT, CHATBOT_TIMEOUT)
    timeout = httpx.Timeout(CHATBOT_TIMEOUT, connect=connect_cap)
    try:
        logger.info(
            "chat/query: forwarding to RAG url=%s timeout_s=%s connect_s=%s",
            CHATBOT_URL,
            CHATBOT_TIMEOUT,
            connect_cap,
        )
        async with httpx.AsyncClient(timeout=timeout) as client:
            payload = {
                "question": request.question,
                "top_k": request.top_k,
                "query_mode": request.query_mode,
            }
            if request.chat_mode is not None:
                payload["chat_mode"] = request.chat_mode
            response = await client.post(
                CHATBOT_URL,
                json=payload,
            )

            if response.status_code != 200:
                error_detail = response.text[:2000] if response.text else ""
                try:
                    err_json = response.json()
                    error_detail = str(err_json.get("detail", err_json))[:2000]
                except Exception:
                    pass
                logger.warning(
                    "chat/query: RAG returned HTTP %s from %s detail=%s",
                    response.status_code,
                    CHATBOT_URL,
                    error_detail[:500],
                )
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Chatbot Service Error from {CHATBOT_URL}: {error_detail}",
                )

            response_data = response.json()
            background_tasks.add_task(
                save_chat_to_db,
                user_id,
                request.question,
                response_data,
                query_mode=request.query_mode,
                chat_mode=request.chat_mode,
                conversation_id=request.conversation_id,
            )
            return response_data

    except httpx.RequestError as exc:
        logger.warning("chat/query: cannot reach RAG url=%s error=%s", CHATBOT_URL, exc)
        detail = f"Không kết nối được Chatbot RAG tại {CHATBOT_URL!s}: {exc!s}."
        if "127.0.0.1" in CHATBOT_URL or "localhost" in CHATBOT_URL:
            detail += (
                " Trên FastAPI Cloud đặt CHATBOT_SERVICE_URL = base URL chatbot "
                "(ví dụ https://...railway.app/) hoặc đầy đủ .../rag/query."
            )
        elif "railway.app" in CHATBOT_URL.lower():
            detail += (
                " Railway cold start có thể rất chậm — thử tăng CHATBOT_TIMEOUT_SECONDS "
                f"(hiện {CHATBOT_TIMEOUT}s) và CHATBOT_CONNECT_TIMEOUT_SECONDS (hiện {CHATBOT_CONNECT_TIMEOUT}s), "
                "hoặc gọi /health của chatbot một lần để đánh thức service."
            )
        raise HTTPException(status_code=503, detail=detail)


@router.get("/history", response_model=ChatHistoryListResponse)
async def list_chat_history(
    skip: int = 0,
    limit: int = 20,
    conversation_id: str | None = None,
    user_id: str = Depends(require_user_id),
):
    """Danh sách lịch sử chat của user đã đăng nhập (mới nhất trước)."""
    lim = max(1, min(limit, 100))
    sk = max(0, skip)
    query_filter: dict[str, Any] = {"user_id": user_id}
    if conversation_id:
        query_filter["conversation_id"] = conversation_id

    total = await chats_collection.count_documents(query_filter)
    cursor = (
        chats_collection.find(query_filter).sort("timestamp", -1).skip(sk).limit(lim)
    )
    docs = await cursor.to_list(length=lim)
    items = [_mongo_doc_to_list_item(d) for d in docs]
    return ChatHistoryListResponse(items=items, total=total, skip=sk, limit=lim)


@router.get("/history/{chat_id}", response_model=ChatHistoryDetail)
async def get_chat_history_detail(chat_id: str, user_id: str = Depends(require_user_id)):
    """Chi tiết một lượt chat — chỉ chủ sở hữu mới đọc được."""
    oid = _parse_object_id(chat_id)
    doc = await chats_collection.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy lịch sử chat.")
    if str(doc.get("user_id")) != str(user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy lịch sử chat.")
    return _mongo_doc_to_detail(doc)
