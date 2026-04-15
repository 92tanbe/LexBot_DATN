import os
from dotenv import load_dotenv

load_dotenv()

URL_MONGODB = os.getenv("URL_MONGODB")
if not URL_MONGODB:
    raise RuntimeError(
        "Biến môi trường URL_MONGODB chưa được cấu hình! "
        "Vui lòng set URL_MONGODB trong Environment Variables trên fastapicloud dashboard."
    )

SECRET_KEY = os.getenv("SECRET_KEY", "changethissecretkey")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
