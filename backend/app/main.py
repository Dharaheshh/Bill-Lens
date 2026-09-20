import asyncio
import json
import logging
import uuid

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select, text, update
from sse_starlette.sse import EventSourceResponse

from app import schemas
from app.config import settings
from app.db import AsyncSessionLocal, engine
from app.models import Base, Bill, Policy, Run, TraceEvent
from app.orchestrator.events import get_or_create_queue
from app.orchestrator.replay import trigger_replay
from app.orchestrator.runner import (
    run_bill_audit_phase1,
    run_bill_audit_phase2,
    run_policy_ingest,
)

logger = logging.getLogger(__name__)

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
    except Exception:  # noqa: BLE001, S110
        pass

    try:
        from app.rag.embed import embedder
        if embedder:
            embed_ok = True
    except Exception:  # noqa: BLE001, S110
        pass

    if settings.LLM_API_KEY:
        llm_ok = True

    return {"db": db_ok, "llm": llm_ok, "embed": embed_ok}


@app.get("/samples", response_model=list[dict])
async def get_samples():
    return [
        {
            "id": "sample-a",
            "kind": "bill",
            "title": "Orthopedic Surgery",
            "description": "Standard room, multiple deductions.",
            "thumb_url": "/mock/sample-a-thumb.png",
            "is_insured": True,
        },
        {
            "id": "sample-b",
            "kind": "bill",
            "title": "Fever & Observation",
            "description": "% SI room cap.",
            "thumb_url": "/mock/sample-b-thumb.png",
            "is_insured": True,
        },
        {
            "id": "sample-c",
            "kind": "bill",
            "title": "Uninsured Consultation",
            "description": "Self-paying patient.",
            "thumb_url": "/mock/sample-c-thumb.png",
            "is_insured": False,
        }
    ]


@app.post("/policies")
async def ingest_policy(background_tasks: BackgroundTasks, file: UploadFile = File(...)):  # noqa: B008
    policy_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    # Save temp
    import os
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".pdf")
    with os.fdopen(fd, "wb") as f:
        f.write(await file.read())

    async with AsyncSessionLocal() as session:
        session.add(Policy(id=policy_id))
        session.add(Run(id=run_id, kind="policy_ingest", policy_id=policy_id, status="starting"))
        await session.commit()

    background_tasks.add_task(run_policy_ingest, run_id, path, policy_id, None, "test-session")
    return {"policy_id": policy_id, "run_id": run_id}


@app.get("/policies/{id}")
async def get_policy(id: str):
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(Policy).where(Policy.id == id))
        policy = res.scalar()
        if not policy:
            return {"terms": {}, "status": "not_found"}
        return {"terms": policy.terms or {}, "status": "done" if policy.terms else "processing"}


class PolicyTermsUpdate(BaseModel):
    terms: dict
    confirmed: bool

@app.put("/policies/{id}/terms", response_model=schemas.ResolvedPolicy)
async def update_policy_terms(id: str, payload: PolicyTermsUpdate):
    async with AsyncSessionLocal() as session:
        await session.execute(update(Policy).where(Policy.id == id).values(terms=payload.terms, confirmed=payload.confirmed))
        await session.commit()
    from app.orchestrator.runner import _build_resolved_policy
    return _build_resolved_policy(payload.terms, is_insured=True)


@app.post("/bills")
async def upload_bill(file: UploadFile = File(...)):  # noqa: B008
    bill_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as session:
        session.add(Bill(id=bill_id, filename=file.filename, is_insured=True))
        await session.commit()
    return {"bill_id": bill_id}


class RunRequest(BaseModel):
    bill_id: str
    policy_id: str | None = None
    auto_confirm: bool | None = False

@app.post("/runs")
async def create_run(req: RunRequest, background_tasks: BackgroundTasks):
    run_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as session:
        session.add(Run(id=run_id, kind="audit", mode="live", bill_id=req.bill_id, policy_id=req.policy_id, status="starting", phase="phase1"))
        await session.commit()

    background_tasks.add_task(run_bill_audit_phase1, run_id, req.bill_id, req.auto_confirm or False)
    return {"run_id": run_id}


@app.get("/runs/{id}")
async def get_run(id: str):
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(Run).where(Run.id == id))
        run = res.scalar()
        if not run:
            return {"status": "not_found"}
        return {"status": run.status, "phase": run.phase, "mode": run.mode}


class ConfirmRunRequest(BaseModel):
    lines: list[schemas.MatchedLine]
    is_insured: bool
    policy_id: str | None = None

@app.put("/runs/{id}/confirm")
async def confirm_run(id: str, req: ConfirmRunRequest, background_tasks: BackgroundTasks):
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(Run).where(Run.id == id))
        run = res.scalar()
        if not run:
            return {"status": "not_found"}
        
        await session.execute(update(Run).where(Run.id == id).values(status="starting", phase="phase2"))
        
        # update bill's verified lines
        if run.bill_id:
            await session.execute(update(Bill).where(Bill.id == run.bill_id).values(verified=[l.model_dump() for l in req.lines]))
            
        await session.commit()
        background_tasks.add_task(run_bill_audit_phase2, id, str(run.bill_id), req.lines, req.is_insured, req.policy_id or str(run.policy_id) if run.policy_id else None)
    return {"status": "starting", "phase": "phase2"}


@app.get("/runs/{id}/stream")
async def run_stream(id: str, request: Request, since: int = 0):
    async def event_generator():
        # Yield missed events first
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(TraceEvent).where(TraceEvent.run_id == id, TraceEvent.seq > since).order_by(TraceEvent.seq))
            for ev in res.scalars():
                yield {"data": json.dumps(ev.data), "event": ev.type, "id": str(ev.seq)}
        
        # Then tail
        queue = get_or_create_queue(id)
        while True:
            if await request.is_disconnected():
                break
            try:
                ev_data = await asyncio.wait_for(queue.get(), timeout=2.0)
                yield {"data": json.dumps(ev_data.get("data", {})), "event": ev_data.get("type"), "id": str(ev_data.get("seq", 0))}
            except asyncio.TimeoutError:
                yield {"event": "ping", "data": "ping"}

    return EventSourceResponse(event_generator())


@app.get("/runs/{id}/events")
async def get_run_events(id: str, since: int = 0):
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(TraceEvent).where(TraceEvent.run_id == id, TraceEvent.seq > since).order_by(TraceEvent.seq))
        return [
            {
                "seq": e.seq,
                "ts_ms": e.ts_ms,
                "agent": e.agent,
                "type": e.type,
                "title": e.title,
                "data": e.data,
            }
            for e in res.scalars()
        ]


@app.get("/runs/{id}/result", response_model=schemas.RunResult)
async def get_run_result(id: str):
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(Run).where(Run.id == id))
        run = res.scalar()
        if not run or not run.result:
            raise HTTPException(status_code=404, detail="Result not found or not ready")
        return run.result


@app.post("/demo/{sample_id}")
async def run_demo(sample_id: str, background_tasks: BackgroundTasks):
    run_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as session:
        session.add(Run(id=run_id, kind="audit", mode="replay", status="starting", phase="phase1"))
        await session.commit()
    background_tasks.add_task(_run_demo_bg, sample_id, run_id)
    return {"run_id": run_id}

async def _run_demo_bg(sample_id: str, run_id: str):
    async with AsyncSessionLocal() as session:
        await trigger_replay(session, sample_id, run_id)
