import logging

logger = logging.getLogger(__name__)

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CatalogItem
from app.rag.embed import embedder
from app.schemas import BillLine, MatchedLine


async def normalize_lines(session: AsyncSession, lines: list[BillLine]) -> list[MatchedLine]:
    results = []
    for line in lines:
        clean_text = line.raw_text.strip().upper()
        
        # 1. Exact Match
        stmt = select(CatalogItem).where(
            (CatalogItem.canonical_name.ilike(clean_text)) |
            (text(":text = ANY(synonyms)")).bindparams(text=clean_text)
        )
        exact_res = await session.execute(stmt)
        exact_match = exact_res.scalars().first()
        
        if exact_match:
            results.append(MatchedLine(
                **line.model_dump(),
                catalog_id=exact_match.id,
                canonical_name=exact_match.canonical_name,
                category=exact_match.category,
                match_method="exact",
                match_score=1.0
            ))
            continue
            
        # 2. Embedding Match (Top-5, but taking Top-1 for now if > 0.7)
        try:
            emb = embedder.embed_query(clean_text)
            if emb:
                stmt = select(CatalogItem, CatalogItem.embedding.cosine_distance(emb).label("dist")) \
                       .order_by("dist").limit(1)
                res = await session.execute(stmt)
                row = res.first()
                if row:
                    cat_item, dist = row
                    score = 1.0 - dist
                    if score > 0.6:  # Threshold
                        results.append(MatchedLine(
                            **line.model_dump(),
                            catalog_id=cat_item.id,
                            canonical_name=cat_item.canonical_name,
                            category=cat_item.category,
                            match_method="embedding",
                            match_score=score
                        ))
                        continue
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Embedding match failed for {clean_text}: {e}")
            
        # 3. LLM Rerank Fallback
        # Skipped safely if LLM not configured
        
        # 4. Unmatched
        results.append(MatchedLine(**line.model_dump()))
        
    return results
