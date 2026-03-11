"""
Ứng dụng FastAPI: chatbot với đăng ký/đăng nhập và lịch sử chat (MongoDB).
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.database import close_mongodb, connect_mongodb
from app.routers import auth_router, chat_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Mở kết nối MongoDB khi start, đóng khi shutdown."""
    await connect_mongodb()
    yield
    await close_mongodb()


app = FastAPI(
    title="Chatbot Backend",
    description="Backend FastAPI: đăng ký, đăng nhập, chat và lịch sử theo tài khoản (MongoDB)",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(auth_router.router)
app.include_router(chat_router.router)


@app.get("/health")
def health_check() -> dict:
    """Kiểm tra trạng thái dịch vụ."""
    return {"status": "ok"}
