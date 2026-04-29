import logging
import os
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel

from app.db.mongodb import chats_collection
from app.core.security import decode_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)

# Local development should default to the local chatbot microservice.
# Production can override this via CHATBOT_SERVICE_URL.
CHATBOT_URL = os.getenv("CHATBOT_SERVICE_URL", "http://127.0.0.1:8001/rag/query")
CHATBOT_TIMEOUT = float(os.getenv("CHATBOT_TIMEOUT_SECONDS", "60"))

class ChatRequest(BaseModel):
    question: str
    top_k: int = 5

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

    timeout = httpx.Timeout(CHATBOT_TIMEOUT, connect=min(15.0, CHATBOT_TIMEOUT))
    try:
        logger.info("chat/query: forwarding to RAG url=%s timeout_s=%s", CHATBOT_URL, CHATBOT_TIMEOUT)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                CHATBOT_URL,
                json={"question": request.question, "top_k": request.top_k},
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
                " Trên fastapicloud, backend và chatbot_rag là hai app riêng: "
                "đặt biến CHATBOT_SERVICE_URL trỏ tới URL đầy đủ của RAG "
                "(ví dụ https://<app-chatbot>.fastapicloud.dev/rag/query)."
            )
        raise HTTPException(status_code=503, detail=detail)
