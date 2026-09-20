"""
Policy Agent: extracts 4 policy terms using search_policy + grounding.
Falls back to not_found on any failure.
"""
import asyncio
import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.client import LLMUnavailable, llm_client
from app.orchestrator.events import RunContext
from app.rag.grounding import validate_term
from app.rag.retrieve import search
from app.schemas import Evidence, PolicyTerm

logger = logging.getLogger(__name__)

TERM_QUERIES = {
    "sum_insured": "sum insured amount coverage limit",
    "room_rent_cap": "room rent limit per day normal room accommodation",
    "copay_pct": "co-payment percentage of admissible claim",
    "proportionate_deduction": "proportionate deduction charges linked to room rent",
}

SYSTEM_PROMPT = """You extract ONE insurance policy term using the search results provided.
Return ONLY JSON: {"found": bool, "value": number|bool|null, "room_cap_kind": "absolute"|"pct_si"|null, "quote": "<VERBATIM text from the chunk ≤300 chars>", "chunk_id": int, "reasoning": "<one sentence>"}
Rules:
- never infer from outside knowledge; if not found, return found:false
- For room rent: use the limit for normal/general (non-ICU) room
- If limit is % of sum insured, set room_cap_kind:"pct_si" and value to the percentage
- If limit is a rupee amount per day, use "absolute"
- quote must be copied VERBATIM from one of the retrieved chunks"""


async def extract_one_term(
    session: AsyncSession,
    document_id: str,
    key: str,
    ctx: RunContext,
) -> PolicyTerm:
    """Extract a single policy term with LLM + grounding validation."""
    ctx.emit("policy", "stage_start", f"Extracting term: {key}")

    query = TERM_QUERIES.get(key, key)
    try:
        chunks = await search(session, f"policy:{document_id}", query, k=4)
    except Exception as e:
        logger.warning("Policy retrieval failed for %s: %s", key, e)
        return PolicyTerm(key=key, status="not_found")  # type: ignore[arg-type]

    ctx.emit("policy", "retrieval", f"Retrieved {len(chunks)} chunks for {key}", data={"query": query, "count": len(chunks)})

    if not chunks:
        return PolicyTerm(key=key, status="not_found")  # type: ignore[arg-type]

    # Register chunk evidence
    for chunk in chunks[:2]:
        ev = Evidence(id="", type="clause", text=chunk["text"][:300], meta={"page": chunk["page"], "similarity": chunk["similarity"], "chunk_id": chunk["chunk_id"]})
        ctx.evidence.add([ev])

    # Try LLM extraction
    chunk_context = "\n\n---\n\n".join(
        f"[Chunk {c['chunk_id']}, Page {c['page']}]\n{c['text'][:600]}" for c in chunks
    )
    user_msg = f"Term to extract: {key}\n\nPolicy chunks:\n{chunk_context}"

    try:
        resp = await llm_client.chat(
            [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_msg}],
            role="agent",
            temperature=0,
            json_mode=True,
        )
        ctx.emit("policy", "llm_call", f"LLM extraction for {key}")

        parsed = json.loads(resp.text)
        if not parsed.get("found"):
            return PolicyTerm(key=key, status="not_found")  # type: ignore[arg-type]

        value = parsed.get("value")
        quote = parsed.get("quote")
        chunk_id = parsed.get("chunk_id")

        # Find chunk text for grounding
        chunk_text = next((c["text"] for c in chunks if c["chunk_id"] == chunk_id), "")
        if not chunk_text and chunks:
            chunk_text = chunks[0]["text"]
            chunk_id = chunks[0]["chunk_id"]

        # Ground the claim
        grounded = validate_term(key, quote, chunk_text, value)
        if not grounded:
            ctx.emit("policy", "warning", f"Grounding failed for {key} — marking not_found")
            return PolicyTerm(key=key, status="not_found")  # type: ignore[arg-type]

        # Find similarity
        similarity = next((c["similarity"] for c in chunks if c["chunk_id"] == chunk_id), 0.0)
        page = next((c["page"] for c in chunks if c["chunk_id"] == chunk_id), 1)

        # Register evidence
        ev = Evidence(id="", type="clause", text=quote or chunk_text[:300], meta={"page": page, "similarity": similarity, "chunk_id": chunk_id})
        [ev_id] = ctx.evidence.add([ev])

        ctx.emit("policy", "finding", f"Extracted {key}: {value}", data={"key": key, "value": value, "page": page})

        return PolicyTerm(
            key=key,  # type: ignore[arg-type]
            status="extracted",
            value=value,
            room_cap_kind=parsed.get("room_cap_kind"),
            quote=quote,
            page=page,
            chunk_id=chunk_id,
            similarity=similarity,
        )

    except LLMUnavailable:
        ctx.emit("policy", "warning", f"LLM unavailable for {key} — marking not_found")
        return PolicyTerm(key=key, status="not_found")  # type: ignore[arg-type]
    except Exception as e:
        logger.warning("Policy extraction failed for %s: %s", key, e)
        return PolicyTerm(key=key, status="not_found")  # type: ignore[arg-type]


async def run_policy_agent(
    session: AsyncSession,
    document_id: str,
    ctx: RunContext,
) -> dict[str, PolicyTerm]:
    """Run Policy Agent for all 4 terms in parallel."""
    ctx.emit("policy", "stage_start", "Policy Agent: extracting 4 terms in parallel")

    tasks = [extract_one_term(session, document_id, key, ctx) for key in TERM_QUERIES]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    terms: dict[str, PolicyTerm] = {}
    for key, result in zip(TERM_QUERIES.keys(), results):
        if isinstance(result, Exception):
            logger.warning("Term %s extraction raised: %s", key, result)
            terms[key] = PolicyTerm(key=key, status="not_found")  # type: ignore[arg-type]
        else:
            terms[key] = result

    ctx.emit("policy", "stage_end", f"Policy Agent: {sum(1 for t in terms.values() if t.status == 'extracted')} of 4 terms extracted")
    return terms
