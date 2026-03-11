"""
Cấu hình ứng dụng: biến môi trường, MongoDB, JWT.
Ưu tiên đọc từ env; mặc định dùng giá trị local.
"""
import os
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Cấu hình chung cho backend."""

    # MongoDB
    mongodb_url: str = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    mongodb_db_name: str = os.getenv("MONGODB_DB_NAME", "chatbot_db")

    # JWT
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "doi-secret-khi-deploy")
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 ngày

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
