from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import text

from app import schemas
from app.config import settings
from app.db import engine
from app.models import Base

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


# --- Phase 1 API Stubs ---

class Sample(BaseModel):
    id: str
    kind: str
    title: str
    description: str
    thumb_url: str
    is_insured: bool

@app.get("/samples", response_model=list[Sample])
async def get_samples():
    return []

@app.post("/policies")
async def ingest_policy():
    return {"policy_id": "test-pol-123", "run_id": "run-test-123"}

@app.get("/policies/{id}")
async def get_policy(id: str):
    return {"terms": {}, "status": "done"}

class PolicyTermsUpdate(BaseModel):
    terms: dict
    confirmed: bool

@app.put("/policies/{id}/terms", response_model=schemas.ResolvedPolicy)
async def update_policy_terms(id: str, payload: PolicyTermsUpdate):
    return schemas.ResolvedPolicy(is_insured=True)

@app.post("/bills")
async def upload_bill():
    return {"bill_id": "test-bill-123"}

class RunRequest(BaseModel):
    bill_id: str
    policy_id: str | None = None
    auto_confirm: bool | None = None

@app.post("/runs")
async def create_run(req: RunRequest):
    return {"run_id": "run-test-123"}

@app.get("/runs/{id}")
async def get_run(id: str):
    return {"status": "awaiting_verification", "phase": "1"}

class ConfirmRunRequest(BaseModel):
    lines: list[schemas.MatchedLine]
    is_insured: bool

@app.put("/runs/{id}/confirm")
async def confirm_run(id: str, req: ConfirmRunRequest):
    return {"status": "done"}

@app.get("/runs/{id}/stream")
async def run_stream(id: str):
    pass

@app.get("/runs/{id}/events")
async def get_run_events(id: str, since: int = 0):
    return []

@app.get("/runs/{id}/result", response_model=schemas.RunResult)
async def get_run_result(id: str):
    raise NotImplementedError()

@app.post("/demo/{sample_id}")
async def run_demo(sample_id: str):
    return {"run_id": "run-demo-123"}
