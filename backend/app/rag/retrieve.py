"""RAG retrieval: dense vector search + keyword hybrid boost."""
import logging
from typing import Any

import numpy as np
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.embed import embedder

logger = logging.getLogger(__name__)

KEYWORD_BOOSTS: dict[str, list[str]] = {
    "room": ["room rent", "room charge", "accommodation"],
    "copay": ["co-pay", "copayment", "co-payment"],
    "sum_insured": ["sum insured", "sum assured", "coverage amount"],
    "proportionate": ["proportionate", "pro-rata", "proportional"],
}


async def search(
    session: AsyncSession,
    scope: str,
    query: str,
    k: int = 5,
) -> list[dict[str, Any]]:
    """
    Search chunks. scope is 'kb' or 'policy:{document_id}'.
    Returns list of {chunk_id, page, heading, text, similarity}.
    """
    results: list[dict] = []

    # 1. Dense vector search
    try:
        q_emb = embedder.embed_query(query)
        if q_emb:
            if scope == "kb":
                sql = text("""
                    SELECT c.id, c.page, c.heading, c.text,
                           1 - (c.embedding <=> CAST(:emb AS vector)) AS similarity
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE d.kind = 'kb'
                    ORDER BY c.embedding <=> CAST(:emb AS vector)
                    LIMIT :k
                """)
            else:
                doc_id = scope.split("policy:")[-1]
                sql = text("""
                    SELECT c.id, c.page, c.heading, c.text,
                           1 - (c.embedding <=> CAST(:emb AS vector)) AS similarity
                    FROM chunks c
                    WHERE c.document_id = CAST(:doc_id AS uuid)
                    ORDER BY c.embedding <=> CAST(:emb AS vector)
                    LIMIT :k
                """)
            params: dict[str, Any] = {"emb": str(q_emb), "k": k * 2}
            if scope != "kb":
                params["doc_id"] = doc_id
            res = await session.execute(sql, params)
            for row in res.fetchall():
                results.append({
                    "chunk_id": row[0],
                    "page": row[1],
                    "heading": row[2],
                    "text": row[3],
                    "similarity": float(row[4]),
                })
    except Exception as e:
        logger.warning("Dense search failed, falling back: %s", e)
        results = await _numpy_fallback(session, scope, query, k * 2)

    # 2. Keyword hybrid boost
    seen_ids = {r["chunk_id"] for r in results}
    query_lower = query.lower()
    boost_terms = []
    for _, terms in KEYWORD_BOOSTS.items():
        for term in terms:
            if term in query_lower:
                boost_terms.append(f"%{term}%")

    if boost_terms:
        try:
            if scope == "kb":
                kw_sql = text("""
                    SELECT c.id, c.page, c.heading, c.text
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE d.kind = 'kb'
                      AND (""" + " OR ".join(f"c.text ILIKE :t{i}" for i in range(len(boost_terms))) + """)
                    LIMIT :k
                """)
            else:
                doc_id = scope.split("policy:")[-1]
                kw_sql = text("""
                    SELECT c.id, c.page, c.heading, c.text
                    FROM chunks c
                    WHERE c.document_id = CAST(:doc_id AS uuid)
                      AND (""" + " OR ".join(f"c.text ILIKE :t{i}" for i in range(len(boost_terms))) + """)
                    LIMIT :k
                """)
            kw_params: dict[str, Any] = {f"t{i}": t for i, t in enumerate(boost_terms)}
            kw_params["k"] = k
            if scope != "kb":
                kw_params["doc_id"] = doc_id
            kw_res = await session.execute(kw_sql, kw_params)
            for row in kw_res.fetchall():
                cid = row[0]
                if cid not in seen_ids:
                    results.append({
                        "chunk_id": cid,
                        "page": row[1],
                        "heading": row[2],
                        "text": row[3],
                        "similarity": 0.6,
                    })
                    seen_ids.add(cid)
                else:
                    # Boost existing
                    for r in results:
                        if r["chunk_id"] == cid:
                            r["similarity"] = max(r["similarity"], 0.6)
        except Exception as e:
            logger.warning("Keyword search failed: %s", e)

    # Sort and return top k
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:k]


async def _numpy_fallback(
    session: AsyncSession,
    scope: str,
    query: str,
    k: int,
) -> list[dict[str, Any]]:
    """In-memory numpy cosine similarity as fallback when pgvector fails."""
    try:
        q_emb = embedder.embed_query(query)
        if not q_emb:
            return []

        if scope == "kb":
            sql = text("""
                SELECT c.id, c.page, c.heading, c.text, c.embedding
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE d.kind = 'kb'
            """)
            params = {}
        else:
            doc_id = scope.split("policy:")[-1]
            sql = text("""
                SELECT c.id, c.page, c.heading, c.text, c.embedding
                FROM chunks c
                WHERE c.document_id = CAST(:doc_id AS uuid)
            """)
            params = {"doc_id": doc_id}

        res = await session.execute(sql, params)
        rows = res.fetchall()
        if not rows:
            return []

        q_arr = np.array(q_emb, dtype=np.float32)
        results = []
        for row in rows:
            emb = row[4]
            if emb is None:
                continue
            arr = np.array(emb, dtype=np.float32)
            sim = float(np.dot(q_arr, arr) / (np.linalg.norm(q_arr) * np.linalg.norm(arr) + 1e-9))
            results.append({"chunk_id": row[0], "page": row[1], "heading": row[2], "text": row[3], "similarity": sim})

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:k]
    except Exception as e:
        logger.error("Numpy fallback also failed: %s", e)
        return []
