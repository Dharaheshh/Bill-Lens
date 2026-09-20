"""Record a live run to a replay file."""
import asyncio
import json
import uuid
from pathlib import Path

from app.db import AsyncSessionLocal
from app.models import Bill, Policy, Run, TraceEvent
from app.orchestrator.runner import (
    run_bill_audit_phase1,
)


async def record(sample_id: str):
    print(f"Recording replay for {sample_id}...")
    run_id = str(uuid.uuid4())
    bill_id = str(uuid.uuid4())
    policy_id = str(uuid.uuid4())

    async with AsyncSessionLocal() as session:
        # Create records
        session.add(Bill(id=bill_id, filename=f"{sample_id}.png", is_insured=True))
        session.add(Policy(id=policy_id))
        session.add(Run(id=run_id, kind="audit", mode="live", bill_id=bill_id, policy_id=policy_id))
        await session.commit()

    print("Phase 1...")
    # Assume we don't do real vision for replay recording unless we want to wait.
    # Actually run_bill_audit_phase1 will use the golden extraction if we give it the sample_id name.
    await run_bill_audit_phase1(run_id, bill_id, auto_confirm=True)

    # If it was auto confirmed, Phase 2 is already run inside Phase 1.
    
    async with AsyncSessionLocal() as session:
        # Fetch events
        from sqlalchemy import select
        res = await session.execute(select(TraceEvent).where(TraceEvent.run_id == run_id).order_by(TraceEvent.seq))
        events = [
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

        # Fetch result
        run_res = await session.execute(select(Run).where(Run.id == run_id))
        run_obj = run_res.scalar()
        result = run_obj.result if run_obj else {}

    out_dir = Path(__file__).parent.parent / "seed" / "replays"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{sample_id}.json"
    
    with open(out_path, "w") as f:  # noqa: ASYNC230
        json.dump({"events": events, "result": result}, f, indent=2)
    
    print(f"Recorded {len(events)} events to {out_path}")


if __name__ == "__main__":
    import sys
    sample = sys.argv[1] if len(sys.argv) > 1 else "sample-a-ortho-insured"
    asyncio.run(record(sample))
