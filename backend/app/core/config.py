import os
from dotenv import load_dotenv

load_dotenv()

URL_MONGODB = os.getenv("URL_MONGODB")
SECRET_KEY = os.getenv("SECRET_KEY", "changethissecretkey")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
