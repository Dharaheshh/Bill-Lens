from fastapi import APIRouter
from sqlalchemy import text

from app.config import settings
from app.db import engine
from app.rag.embed import embedder

router = APIRouter()


@router.get("/health")
async def health_check() -> dict:
    db_ok = False
    embed_ok = False
    llm_ok = False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001, S110
        pass
    try:
        if embedder and embedder.model:
            embed_ok = True
    except Exception:  # noqa: BLE001, S110
        pass
    try:
        if settings.LLM_API_KEY:
            llm_ok = True
    except Exception:  # noqa: BLE001, S110
        pass
    return {"db": db_ok, "llm": llm_ok, "embed": embed_ok}
