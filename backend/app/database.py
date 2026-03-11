"""
Kết nối MongoDB dùng Motor (async).
Dùng trong lifespan của FastAPI để mở/đóng khi start/shutdown.
"""
from motor.motor_asyncio import AsyncIOMotorClient

from app.config import settings

# Client toàn cục; khởi tạo trong lifespan
_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    """Lấy MongoDB client. Gọi sau khi đã start app (lifespan)."""
    if _client is None:
        raise RuntimeError("MongoDB chưa được kết nối. Kiểm tra lifespan.")
    return _client


def get_database():
    """Lấy database MongoDB (để truy cập collections)."""
    return get_client()[settings.mongodb_db_name]


async def connect_mongodb():
    """Kết nối MongoDB khi ứng dụng khởi động."""
    global _client
    _client = AsyncIOMotorClient(
        settings.mongodb_url,
        serverSelectionTimeoutMS=5000,
    )
    # Kiểm tra kết nối
    await _client.admin.command("ping")


async def close_mongodb():
    """Đóng kết nối khi shutdown."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
