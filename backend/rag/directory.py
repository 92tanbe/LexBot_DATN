from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())
from os import getenv
TOPIC_DB_PATH = "chroma_db_law"
ST_MODEL_PATH = "keepitreal/vietnamese-sbert"
ENVIRONMENT = "development"
ACCESS_TOKEN_KEY= getenv("ACCESS_TOKEN_KEY")

