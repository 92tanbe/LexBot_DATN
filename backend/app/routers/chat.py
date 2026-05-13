import logging
import os
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, Field

from app.db.mongodb import chats_collection
from app.core.security import decode_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)


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

class ChatRequest(BaseModel):
    question: str
    top_k: int = 5
    query_mode: Literal["fast", "thinking"] = Field(
        default="fast",
        description="fast hoặc thinking — forward sang chatbot ChatRequest.query_mode",
    )
    chat_mode: Literal["tra_cuu_pdf", "phan_tich"] | None = Field(
        default=None,
        description="tra_cuu_pdf: trích VB từ PDF chatbot. None: không gửi chat_mode.",
    )

async def save_chat_to_db(user_id: str, question: str, response_data: dict):
    try:
        chat_document = {
            "user_id": user_id,
            "question": question,
            "response": response_data,
            "timestamp": datetime.utcnow()
        }
        await chats_collection.insert_one(chat_document)
    except Exception as e:
        print(f"Error saving chat to db: {e}")

@router.post("/query")
async def chat_query(request: ChatRequest, background_tasks: BackgroundTasks, token: str = Depends(oauth2_scheme)):
    """
    Forward the chat query from the frontend directly to the RAG Chatbot Microservice.
    """
    user_id = "guest"
    if token:
        try:
            payload = decode_token(token)
            user_id = payload.get("sub", "guest")
        except:
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
                    payload = response.json()
                    error_detail = str(payload.get("detail", payload))[:2000]
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
            background_tasks.add_task(save_chat_to_db, user_id, request.question, response_data)
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
