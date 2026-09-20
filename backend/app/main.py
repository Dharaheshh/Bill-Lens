from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.db import engine
from app.models import Base
from sqlalchemy import text
import openai

app = FastAPI(title="BillLens API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_event():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.get("/health")
async def health_check():
    db_ok = False
    embed_ok = False
    llm_ok = False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    try:
        from app.rag.embed import embedder
        if embedder:
            embed_ok = True
    except Exception:
        pass

    try:
        if settings.LLM_API_KEY:
            llm_ok = True # Minimal check for phase 0 to prevent blocking if external API down
    except Exception:
        pass
        
    return {"db": db_ok, "llm": llm_ok, "embed": embed_ok}
