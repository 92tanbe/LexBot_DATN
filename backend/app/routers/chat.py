from fastapi import APIRouter, HTTPException, BackgroundTasks
import httpx
import os
from pydantic import BaseModel
import json

router = APIRouter(prefix="/chat", tags=["Chat"])

# Use environment variable or default to the user's specific deployment URL
CHATBOT_URL = os.getenv("CHATBOT_SERVICE_URL", "https://chatbot-rag.fastapicloud.dev/rag/query")

class ChatRequest(BaseModel):
    question: str
    top_k: int = 5

@router.post("/query")
async def chat_query(request: ChatRequest):
    """
    Forward the chat query from the frontend directly to the RAG Chatbot Microservice.
    """
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
            
            return response.json()
            
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"Error connecting to Chatbot Service: {str(exc)}")
