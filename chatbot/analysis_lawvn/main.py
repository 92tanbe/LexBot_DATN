"""Entry point cho FastAPI Cloud / uvicorn.

FastAPI Cloud CLI mac dinh tim file `main.py` chua bien `app` o thu muc goc deploy.
File nay chi re-export FastAPI app tu app.main de tuan thu convention do.

Chay local:
    cd chatbot
    uvicorn main:app --port 8001 --reload

Deploy:
    cd chatbot
    fastapicloud deploy
"""
from app.main import app  # noqa: F401  (re-export)

__all__ = ["app"]
