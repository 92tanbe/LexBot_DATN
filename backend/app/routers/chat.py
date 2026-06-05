import logging
from datetime import datetime
from typing import Any

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
    ChatProviderInfo,
    ChatProvidersResponse,
    ChatQueryRequest,
    LegalChatRequest,
    LegalChatResponse,
)
from app.services.chatbot_providers import registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)
oauth2_required = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=True)


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
    chatbot_provider: str,
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
            "chatbot_provider": chatbot_provider,
            "conversation_id": conversation_id,
        }
        await chats_collection.insert_one(chat_document)
    except Exception as e:
        logger.warning("Lưu chat vào MongoDB thất bại: %s", e)


def _mongo_doc_to_list_item(doc: dict[str, Any]) -> ChatHistoryItem:
    resp = doc.get("response") or {}
    if not isinstance(resp, dict):
        resp = {}
    provider = doc.get("chatbot_provider") or resp.get("chatbot_provider") or "rag_v1"
    return ChatHistoryItem(
        id=str(doc["_id"]),
        user_id=str(doc.get("user_id", "")),
        question=str(doc.get("question", "")),
        preview_answer=_preview_from_response(resp),
        query_mode=doc.get("query_mode") or "fast",
        chat_mode=doc.get("chat_mode"),
        chatbot_provider=provider,
        conversation_id=doc.get("conversation_id"),
        created_at=_doc_created_at(doc),
    )


def _mongo_doc_to_detail(doc: dict[str, Any]) -> ChatHistoryDetail:
    resp = doc.get("response") or {}
    if not isinstance(resp, dict):
        resp = {}
    provider = doc.get("chatbot_provider") or resp.get("chatbot_provider") or "rag_v1"
    return ChatHistoryDetail(
        id=str(doc["_id"]),
        user_id=str(doc.get("user_id", "")),
        question=str(doc.get("question", "")),
        query_mode=doc.get("query_mode") or "fast",
        chat_mode=doc.get("chat_mode"),
        chatbot_provider=provider,
        conversation_id=doc.get("conversation_id"),
        created_at=_doc_created_at(doc),
        response=resp,
    )


@router.get("/providers", response_model=ChatProvidersResponse)
async def list_chat_providers():
    """Danh sách microservice chatbot — frontend dùng để chọn server."""
    items = registry.list_providers()
    providers = [
        ChatProviderInfo(
            id=p.id,
            name=p.name,
            description=p.description,
            base_url=p.base_url,
            enabled=p.enabled,
            modes=p.modes,
            neo4j_uri_hint=p.neo4j_uri_hint,
            neo4j_database=p.neo4j_database,
        )
        for p in items
    ]
    return ChatProvidersResponse(providers=providers, default_provider="rag_v1")


@router.post("/query")
async def chat_query(
    request: ChatQueryRequest,
    background_tasks: BackgroundTasks,
    token: str = Depends(oauth2_scheme),
):
    """
    Forward câu hỏi tới microservice chatbot được chọn (RAG v1 hoặc Graph v2).
    """
    user_id = "guest"
    if token:
        try:
            payload = decode_token(token)
            user_id = payload.get("sub", "guest")
        except Exception:
            pass

    provider = request.chatbot_provider or "rag_v1"

    if provider == "graph_v2" and request.chat_mode == "tra_cuu_pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Chế độ tra cứu PDF chỉ hỗ trợ trên LexBot RAG v1. "
                "Hãy chuyển server hoặc chọn chế độ tra cứu/ phân tích khác."
            ),
        )

    try:
        response_data = await registry.forward(request)
        background_tasks.add_task(
            save_chat_to_db,
            user_id,
            request.question,
            response_data,
            query_mode=request.query_mode,
            chat_mode=request.chat_mode,
            chatbot_provider=provider,
            conversation_id=request.conversation_id,
        )
        return response_data

    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except httpx.RequestError as exc:
        info = registry.get_provider(provider)
        logger.warning("chat/query: cannot reach provider=%s error=%s", provider, exc)
        raise HTTPException(
            status_code=503,
            detail=f"Không kết nối được {info.name} tại {info.base_url}: {exc!s}.",
        ) from exc


@router.post("/legal", response_model=LegalChatResponse)
async def legal_chat(
    request: LegalChatRequest,
    background_tasks: BackgroundTasks,
    token: str = Depends(oauth2_scheme),
):
    """
    Proxy tới Agentic Graph RAG qua DATN backend để hỗ trợ hội thoại pháp luật nhiều lượt.
    """
    user_id = "guest"
    if token:
        try:
            payload = decode_token(token)
            user_id = payload.get("sub", "guest")
        except Exception:
            pass

    try:
        response_data = await registry.forward_legal_chat(request)
        background_tasks.add_task(
            save_chat_to_db,
            user_id,
            request.message,
            response_data,
            query_mode="thinking",
            chat_mode="phan_tich",
            chatbot_provider="graph_v2",
            conversation_id=response_data.get("case_id") or request.case_id,
        )
        return response_data
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except httpx.RequestError as exc:
        info = registry.get_provider("graph_v2")
        logger.warning("chat/legal: cannot reach provider=%s error=%s", info.id, exc)
        raise HTTPException(
            status_code=503,
            detail=f"Không kết nối được {info.name} tại {info.base_url}: {exc!s}.",
        ) from exc


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
