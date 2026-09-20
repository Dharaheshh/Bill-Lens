"""Policy and calc tools: search_policy, get_clause, calc_room_cap."""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.retrieve import search
from app.schemas import Evidence
from app.tools.registry import ToolResult

logger = logging.getLogger(__name__)


async def search_policy(session: AsyncSession, document_id: str, query: str, k: int = 4) -> ToolResult:
    """Search chunks of THIS run's policy document."""
    results = await search(session, f"policy:{document_id}", query, k)
    evidence = [
        Evidence(
            id="",
            type="clause",
            text=r["text"][:500],
            meta={"page": r["page"], "similarity": r["similarity"], "chunk_id": r["chunk_id"], "heading": r["heading"]},
        )
        for r in results
    ]
    return ToolResult(
        ok=bool(results),
        data=[{"chunk_id": r["chunk_id"], "page": r["page"], "heading": r["heading"], "text": r["text"][:500], "similarity": r["similarity"]} for r in results],
        summary=f"Found {len(results)} policy chunks for query '{query[:40]}'",
        evidence=evidence,
    )


async def search_kb(session: AsyncSession, query: str, k: int = 3) -> ToolResult:
    """Search shared knowledge base chunks."""
    results = await search(session, "kb", query, k)
    evidence = [
        Evidence(
            id="",
            type="kb",
            text=r["text"][:500],
            meta={"page": r["page"], "similarity": r["similarity"], "chunk_id": r["chunk_id"]},
        )
        for r in results
    ]
    return ToolResult(
        ok=bool(results),
        data=[{"chunk_id": r["chunk_id"], "page": r["page"], "text": r["text"][:300], "similarity": r["similarity"]} for r in results],
        summary=f"Found {len(results)} KB chunks for '{query[:40]}'",
        evidence=evidence,
    )


async def get_clause(session: AsyncSession, chunk_id: int) -> ToolResult:
    """Get full chunk text and neighbors."""
    from sqlalchemy import text
    try:
        sql = text("SELECT id, document_id, page, heading, text FROM chunks WHERE id = :cid")
        res = await session.execute(sql, {"cid": chunk_id})
        row = res.fetchone()
        if not row:
            return ToolResult(ok=False, data={}, summary=f"Chunk {chunk_id} not found")

        # Get neighbors
        neighbor_sql = text("""
            SELECT id, text FROM chunks
            WHERE document_id = :doc_id AND id BETWEEN :lo AND :hi
            ORDER BY id
        """)
        neighbor_res = await session.execute(neighbor_sql, {"doc_id": str(row[1]), "lo": chunk_id - 1, "hi": chunk_id + 1})
        neighbors = [r[1] for r in neighbor_res.fetchall() if r[0] != chunk_id]

        chunk_data = {
            "chunk_id": row[0],
            "page": row[2],
            "heading": row[3],
            "text": row[4],
            "neighbors": neighbors,
        }
        evidence = [Evidence(id="", type="clause", text=row[4][:500], meta={"page": row[2], "chunk_id": chunk_id})]
        return ToolResult(ok=True, data=chunk_data, summary=f"Chunk {chunk_id}: page {row[2]}", evidence=evidence)
    except Exception as e:  # noqa: BLE001
        logger.warning("get_clause failed: %s", e)
        return ToolResult(ok=False, data={}, summary=f"Error: {e}")


async def calc_room_cap(sum_insured: float, pct: float) -> ToolResult:
    """Compute absolute room cap from % of sum insured."""
    cap = round(sum_insured * pct / 100, 2)
    text = f"{pct}% of ₹{sum_insured:,.0f} = ₹{cap:,.0f}/day"
    evidence = [Evidence(id="", type="calc", text=text)]
    return ToolResult(
        ok=True,
        data={"cap_per_day": cap},
        summary=f"Room cap = ₹{cap:,.0f}/day",
        evidence=evidence,
    )
