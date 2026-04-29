import os
from pathlib import Path

from peewee import MySQLDatabase
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parent / ".env")


DB_NAME = "law"
DB_USER = "root"
DB_PASSWORD = os.getenv("MYSQL_PASSWORD")
DB_HOST = "127.0.0.1"
DB_PORT = 3306

db = MySQLDatabase(
    database=DB_NAME,
    user=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    port=DB_PORT,
)
