from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from fastapi.security import OAuth2PasswordBearer
import httpx
import os
from pydantic import BaseModel
import json
from datetime import datetime
from app.db.mongodb import chats_collection
from app.core.security import decode_token

router = APIRouter(prefix="/chat", tags=["Chat"])

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login", auto_error=False)

# Use environment variable or default to the user's specific deployment URL
CHATBOT_URL = os.getenv("CHATBOT_SERVICE_URL", "https://chatbot-rag.fastapicloud.dev/rag/query")

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

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                CHATBOT_URL,
                json={"question": request.question, "top_k": request.top_k}
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code, 
                    detail=f"Chatbot Service Error: {response.text}"
                )
            
            response_data = response.json()
            
            background_tasks.add_task(save_chat_to_db, user_id, request.question, response_data)
            
            return response_data
            
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"Error connecting to Chatbot Service: {str(exc)}")
