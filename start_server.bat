@echo off
echo ============================================
echo   RAG Law Chatbot Server - Startup Script
echo ============================================
echo.

:: Kiem tra FAISS index
if exist faiss_index.bin (
    echo [OK] FAISS index da co san.
) else (
    echo [!] Chua co FAISS index. Dang build tu dau...
    echo     [Luu y: Qua trinh nay co the mat vai phut do API rate limit]
    .\venv\Scripts\python rag_engine.py --build
    if errorlevel 1 (
        echo [LOI] Khong the build FAISS index!
        pause
        exit /b 1
    )
    echo [OK] Index da duoc tao thanh cong!
)

echo.
echo [*] Khoi dong FastAPI server tai http://localhost:8000
echo [*] API docs: http://localhost:8000/docs
echo.
.\venv\Scripts\uvicorn server:app --host 0.0.0.0 --port 8000 --reload
