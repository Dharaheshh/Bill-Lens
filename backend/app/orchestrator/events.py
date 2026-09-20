"""
Orchestrator events: RunContext, EvidenceStore, trace emission.
"""
import asyncio
import logging
import time
from typing import Any

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TraceEvent as TraceEventModel
from app.schemas import Evidence, TraceEvent

logger = logging.getLogger(__name__)

# In-memory SSE queues: run_id -> asyncio.Queue
_run_queues: dict[str, asyncio.Queue] = {}


def get_or_create_queue(run_id: str) -> asyncio.Queue:
    if run_id not in _run_queues:
        _run_queues[run_id] = asyncio.Queue()
    return _run_queues[run_id]


def drop_queue(run_id: str) -> None:
    _run_queues.pop(run_id, None)


class EvidenceStore:
    def __init__(self) -> None:
        self._items: list[Evidence] = []
        self._counter = 0

    def add(self, evidence_list: list[Evidence]) -> list[str]:
        ids = []
        for ev in evidence_list:
            self._counter += 1
            ev_id = f"E{self._counter}"
            ev = Evidence(id=ev_id, type=ev.type, text=ev.text, meta=ev.meta)
            self._items.append(ev)
            ids.append(ev_id)
        return ids

    def get_all(self) -> list[Evidence]:
        return list(self._items)

    def get_ids(self) -> set[str]:
        return {e.id for e in self._items}

    def get_by_id(self, ev_id: str) -> Evidence | None:
        for e in self._items:
            if e.id == ev_id:
                return e
        return None


class RunContext:
    def __init__(
        self,
        run_id: str,
        session: AsyncSession,
        mode: str = "live",
    ) -> None:
        self.run_id = run_id
        self.session = session
        self.mode = mode
        self.evidence = EvidenceStore()
        self.t0 = time.time()
        self._seq = 0
        self._queue = get_or_create_queue(run_id)

        # stats
        self.tool_calls = 0
        self.llm_calls = 0
        self.duration_ms = 0

    def _ms(self) -> int:
        return int((time.time() - self.t0) * 1000)

    def emit(
        self,
        agent: str,
        event_type: str,
        title: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        self._seq += 1
        event = TraceEvent(
            run_id=self.run_id,
            seq=self._seq,
            ts_ms=self._ms(),
            agent=agent,  # type: ignore[arg-type]
            type=event_type,  # type: ignore[arg-type]
            title=title,
            data=data or {},
        )
        # Persist to DB (fire-and-forget; if it fails, log it)
        asyncio.create_task(self._persist_event(event))
        # Push to SSE queue
        try:
            self._queue.put_nowait(event.model_dump())
        except asyncio.QueueFull:
            pass

        if event_type == "tool_call":
            self.tool_calls += 1
        elif event_type == "llm_call":
            self.llm_calls += 1

    async def _persist_event(self, event: TraceEvent) -> None:
        try:
            stmt = insert(TraceEventModel).values(
                run_id=self.run_id,
                seq=event.seq,
                ts_ms=event.ts_ms,
                agent=event.agent,
                type=event.type,
                title=event.title,
                data=event.data,
            ).on_conflict_do_nothing()
            await self.session.execute(stmt)
            await self.session.commit()
        except Exception as e:  # noqa: BLE001
            logger.debug("Failed to persist trace event: %s", e)

    def agent_stats(self) -> dict[str, int]:
        self.duration_ms = self._ms()
        return {
            "tool_calls": self.tool_calls,
            "evidence_items": len(self.evidence.get_all()),
            "llm_calls": self.llm_calls,
            "duration_ms": self.duration_ms,
        }
