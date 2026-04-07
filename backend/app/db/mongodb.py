from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import URL_MONGODB

client = AsyncIOMotorClient(URL_MONGODB)
database = client["lexbot_db"]

users_collection = database["users"]
