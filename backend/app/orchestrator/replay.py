"""Replay mode: loads recorded trace events and result, simulates live run."""
import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Run, TraceEvent
from app.orchestrator.events import get_or_create_queue

logger = logging.getLogger(__name__)


async def trigger_replay(session: AsyncSession, sample_id: str, run_id: str) -> None:
    """Run a replay simulation for a given sample."""
    replay_file = Path(__file__).parent.parent / "seed" / "replays" / f"{sample_id}.json"
    if not replay_file.exists():
        logger.error("Replay file not found: %s", replay_file)
        await session.execute(
            insert(Run).values(id=run_id, kind="audit", mode="replay", status="failed", error="Replay file not found")
        )
        await session.commit()
        return

    with open(replay_file) as f:
        data = json.load(f)
    
    events = data.get("events", [])
    result = data.get("result", {})
    if result:
        result["run_id"] = run_id
        result["mode"] = "replay"

    # Create run
    await session.execute(
        insert(Run).values(id=run_id, kind="audit", mode="replay", status="running", phase="phase1")
    )
    await session.commit()

    queue = get_or_create_queue(run_id)

    # Simulate events
    for i, ev_data in enumerate(events):
        ev_data["run_id"] = run_id
        try:
            queue.put_nowait(ev_data)
        except asyncio.QueueFull:
            pass
        
        # Persist event
        await session.execute(
            insert(TraceEvent).values(
                run_id=run_id,
                seq=ev_data.get("seq", i + 1),
                ts_ms=ev_data.get("ts_ms", 0),
                agent=ev_data.get("agent", "orchestrator"),
                type=ev_data.get("type", "info"),
                title=ev_data.get("title", ""),
                data=ev_data.get("data", {}),
            )
        )
        
        if ev_data.get("type") == "stage_end" and ev_data.get("agent") == "orchestrator":
            if "extract" in ev_data.get("title", "").lower() or "awaiting" in ev_data.get("title", "").lower():
                await session.execute(update(Run).where(Run.id == run_id).values(status="awaiting_verification"))
                await session.commit()
                # Pause for "user verification" in demo
                await asyncio.sleep(2)
                await session.execute(update(Run).where(Run.id == run_id).values(status="running", phase="phase2"))
                await session.commit()
        
        # Delay based on ts_ms diff? Or just a flat short delay for fast demo.
        await asyncio.sleep(0.05)
        if i % 10 == 0:
            await session.commit()

    # Finish run
    await session.execute(
        update(Run).where(Run.id == run_id).values(status="done", result=result)
    )
    await session.commit()
