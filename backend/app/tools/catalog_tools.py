"""Catalog tools: search_catalog, lookup_reference_price."""
import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogItem
from app.rag.embed import embedder
from app.schemas import Evidence
from app.tools.registry import ToolResult

logger = logging.getLogger(__name__)


async def search_catalog(session: AsyncSession, query: str, k: int = 5) -> ToolResult:
    """Search catalog items by embedding similarity."""
    try:
        q_emb = embedder.embed_query(query)
        if q_emb:
            sql = text("""
                SELECT id, canonical_name, category, non_payable, ref_price_low, ref_price_high,
                       1 - (embedding <=> CAST(:emb AS vector)) AS similarity
                FROM catalog_items
                ORDER BY embedding <=> CAST(:emb AS vector)
                LIMIT :k
            """)
            res = await session.execute(sql, {"emb": str(q_emb), "k": k})
            rows = res.fetchall()
            results = [
                {
                    "catalog_id": r[0],
                    "name": r[1],
                    "category": r[2],
                    "non_payable": r[3],
                    "similarity": float(r[6]),
                }
                for r in rows
            ]
        else:
            # Keyword fallback
            sql = text("SELECT id, canonical_name, category, non_payable, ref_price_low, ref_price_high FROM catalog_items WHERE canonical_name ILIKE :q LIMIT :k")
            res = await session.execute(sql, {"q": f"%{query}%", "k": k})
            rows = res.fetchall()
            results = [{"catalog_id": r[0], "name": r[1], "category": r[2], "non_payable": r[3], "similarity": 0.6} for r in rows]

        evidence = [
            Evidence(
                id="",
                type="catalog",
                text=f"Catalog: {r['name']} ({r['category']}, non_payable={r['non_payable']})",
                meta={"catalog_id": r["catalog_id"], "similarity": r["similarity"]},
            )
            for r in results
        ]
        return ToolResult(ok=bool(results), data=results, summary=f"Found {len(results)} catalog items for '{query}'", evidence=evidence)
    except Exception as e:  # noqa: BLE001
        logger.warning("search_catalog failed: %s", e)
        return ToolResult(ok=False, data=[], summary=f"Catalog search error: {e}")


async def lookup_reference_price(session: AsyncSession, catalog_id: int) -> ToolResult:
    """Get reference price range for a catalog item."""
    try:
        res = await session.execute(select(CatalogItem).where(CatalogItem.id == catalog_id))
        item = res.scalar()
        if not item:
            return ToolResult(ok=False, data={}, summary=f"Catalog item {catalog_id} not found")

        data = {
            "catalog_id": catalog_id,
            "name": item.canonical_name,
            "low": item.ref_price_low,
            "high": item.ref_price_high,
            "unit": item.ref_unit,
            "source": item.ref_source or "DEMO_REFERENCE",
        }
        evidence = [Evidence(
            id="",
            type="catalog",
            text=f"Reference: {item.canonical_name} ₹{item.ref_price_low}–₹{item.ref_price_high} ({item.ref_source or 'DEMO_REFERENCE'})",
            meta={"catalog_id": catalog_id},
        )]
        return ToolResult(ok=True, data=data, summary=f"Ref price for {item.canonical_name}: ₹{item.ref_price_low}–{item.ref_price_high}", evidence=evidence)
    except Exception as e:  # noqa: BLE001
        logger.warning("lookup_reference_price failed: %s", e)
        return ToolResult(ok=False, data={}, summary=f"Error: {e}")
