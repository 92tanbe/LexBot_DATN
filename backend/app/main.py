from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import auth, chat

app = FastAPI(title="LexBot API", version="1.0.0")

# CORS — cho phép frontend (local dev + Vercel production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://lex-bot-datn.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router)
app.include_router(chat.router)


@app.get("/")
def root():
    return {"message": "LexBot API đang chạy 🚀"}


@app.get("/test-db")
async def test_db():
    try:
        from app.db.mongodb import users_collection
        import traceback
        count = await users_collection.count_documents({})
        return {"status": "ok", "count": count}
    except Exception as e:
        import traceback
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}