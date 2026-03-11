# =============================================================================
# config/settings.py
# Cấu hình toàn bộ project LexBot
# =============================================================================

import os
from dataclasses import dataclass

@dataclass
class Neo4jConfig:
    """Kết nối Neo4j - thay bằng thông tin thực của bạn"""
    uri: str = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    # Neo4j AuraDB (cloud): "neo4j+s://xxxx.databases.neo4j.io"
    # Neo4j local:           "bolt://localhost:7687"
    username: str = os.getenv("NEO4J_USERNAME", "neo4j")
    password: str = os.getenv("NEO4J_PASSWORD", "your_password_here")
    database: str = os.getenv("NEO4J_DATABASE", "neo4j")

@dataclass
class GeminiConfig:
    """Google Gemini API"""
    api_key: str = os.getenv("API_KEY") or os.getenv("GEMINI_API_KEY", "your_gemini_key_here")
    model: str = "gemini-2.0-flash"
    max_tokens: int = 2048

@dataclass
class DataConfig:
    """Đường dẫn tới file dữ liệu"""
    blhs_csv: str = "data/blhs_2025_from_text.csv"
    giaothong_csv: str = "data/giaothong.csv"

# Singleton instances
NEO4J = Neo4jConfig()
GEMINI = GeminiConfig()
DATA = DataConfig()

