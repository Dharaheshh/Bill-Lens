"""RAG ingestion: PDF → chunks → fastembed → pgvector."""
import logging
import re
import uuid
from pathlib import Path

import pymupdf
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk, Document
from app.rag.embed import embedder

logger = logging.getLogger(__name__)

_HEADING_RE = re.compile(r"(^\d+[\.\d]*\s+[A-Z]|^[A-Z]{3,})", re.MULTILINE)


def _split_into_chunks(text: str, page: int, target_min: int = 400, target_max: int = 900, overlap: int = 100) -> list[dict]:
    """Split text into chunks by heading or size, with overlap."""
    chunks = []
    # Split by ## headings first
    parts = re.split(r"\n(#{1,3} .+)\n", text)
    
    current_heading = "General"
    current_text = ""
    
    for part in parts:
        if part.startswith("#"):
            if current_text.strip() and len(current_text.strip()) > 50:
                chunks.append({"heading": current_heading, "text": current_text.strip(), "page": page})
            current_heading = part.lstrip("# ").strip()
            current_text = ""
        else:
            current_text += part

    if current_text.strip() and len(current_text.strip()) > 50:
        chunks.append({"heading": current_heading, "text": current_text.strip(), "page": page})

    # If no heading splits happened or chunks are too big, do size-based splitting
    result = []
    for chunk in chunks:
        text_part = chunk["text"]
        if len(text_part) <= target_max:
            result.append(chunk)
        else:
            # Size-based split
            words = text_part.split()
            current = []
            current_len = 0
            for word in words:
                current.append(word)
                current_len += len(word) + 1
                if current_len >= target_min:
                    result.append({
                        "heading": chunk["heading"],
                        "text": " ".join(current),
                        "page": chunk["page"],
                    })
                    # Overlap: keep last few words
                    overlap_words = current[-max(1, overlap // 6):]
                    current = list(overlap_words)
                    current_len = sum(len(w) + 1 for w in current)
            if current:
                result.append({
                    "heading": chunk["heading"],
                    "text": " ".join(current),
                    "page": chunk["page"],
                })

    return result or [{"heading": "General", "text": text[:900], "page": page}]


async def ingest_pdf(
    session: AsyncSession,
    pdf_path: str | Path,
    kind: str,
    name: str,
    session_id: str | None = None,
) -> uuid.UUID:
    """Ingest a PDF: extract text, chunk, embed, store. Returns document_id."""
    pdf_path = Path(pdf_path)
    doc_id = uuid.uuid4()

    # Extract text per page
    try:
        pdf_doc = pymupdf.open(str(pdf_path))
    except Exception as e:
        logger.error("Failed to open PDF %s: %s", pdf_path, e)
        raise

    page_count = len(pdf_doc)
    all_chunks: list[dict] = []

    for page_num in range(page_count):
        page = pdf_doc.load_page(page_num)
        text = page.get_text("text")  # type: ignore[attr-defined]
        if not text or len(text.strip()) < 50:
            logger.warning("Page %d of %s has very little text (%d chars)", page_num + 1, name, len(text or ""))
            continue
        chunks = _split_into_chunks(text, page_num + 1)
        all_chunks.extend(chunks)

    pdf_doc.close()

    # Store document
    document = Document(
        id=doc_id,
        kind=kind,
        name=name,
        session_id=session_id,
        page_count=page_count,
    )
    session.add(document)
    await session.flush()

    if not all_chunks:
        logger.warning("No chunks extracted from %s", name)
        await session.commit()
        return doc_id

    # Embed all chunks in one batch
    texts = [c["text"] for c in all_chunks]
    try:
        embeddings = list(embedder.embed_passages(texts))
    except Exception as e:  # noqa: BLE001
        logger.error("Embedding failed for %s: %s", name, e)
        embeddings = [None] * len(texts)

    for chunk_data, emb in zip(all_chunks, embeddings):
        chunk = Chunk(
            document_id=doc_id,
            page=chunk_data["page"],
            heading=chunk_data["heading"],
            text=chunk_data["text"],
            embedding=emb,
        )
        session.add(chunk)

    await session.commit()
    logger.info("Ingested %s: %d pages, %d chunks", name, page_count, len(all_chunks))
    return doc_id
