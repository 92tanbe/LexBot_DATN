import redis
from dotenv import load_dotenv
import os
from pathlib import Path


load_dotenv()
IS_DOCKER = Path("/.dockerenv").exists()
redis_host = "redis" if IS_DOCKER else "localhost"
redis_port = 6379
redis_db = 0
redis_password = os.getenv("REDIS_PASSWORD") or None
redis_ttl_seconds = 86400

redisClient = redis.Redis(
    host=redis_host,
    port=redis_port,
    db=redis_db,
    password=redis_password,
    socket_connect_timeout=5,
    socket_timeout=5,
)

if redisClient.ping():
    print('Connected to Redis server')
else:
    print('Failed to connect to Redis server')
