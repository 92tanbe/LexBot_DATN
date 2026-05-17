@echo off
cd /d "%~dp0"
echo LexBot API: http://127.0.0.1:8000  (canh chatbot RAG neu can: CHATBOT_SERVICE_URL)
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
pause
