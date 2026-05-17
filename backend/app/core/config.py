import logging
import os
from dotenv import load_dotenv

load_dotenv()

_logger = logging.getLogger(__name__)

# Production (FastAPI Cloud): bắt buộc URL_MONGODB trong env.
# Local: nếu chưa set thì fallback MongoDB máy dev để uvicorn vẫn khởi động được.
URL_MONGODB = (os.getenv("URL_MONGODB") or "").strip()
if not URL_MONGODB:
    URL_MONGODB = "mongodb://127.0.0.1:27017"
    _logger.warning(
        "URL_MONGODB chưa set — dùng %s (dev). "
        "Thêm URL_MONGODB vào backend/.env nếu dùng Atlas hoặc cổng khác.",
        URL_MONGODB,
    )

SECRET_KEY = os.getenv("SECRET_KEY", "changethissecretkey")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
