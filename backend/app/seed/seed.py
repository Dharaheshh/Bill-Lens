import asyncio
import csv
import os
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal, engine
from app.models import CatalogItem, Chunk, Document
from app.rag.embed import embedder


async def seed_catalog(session: AsyncSession):
    # Check if catalog exists
    res = await session.execute(select(CatalogItem).limit(1))
    if res.scalar() is not None:
        print("Catalog already seeded.")
        return
    
    catalog_file = os.path.join(os.path.dirname(__file__), 'catalog.csv')
    items = []
    texts_to_embed = []
    
    with open(catalog_file, 'r', encoding='utf-8') as f:  # noqa: ASYNC230
        reader = csv.DictReader(f)
        for row in reader:
            synonyms = [s.strip() for s in row['synonyms'].split('|') if s.strip()]
            text_for_embed = f"{row['canonical_name']} {' '.join(synonyms)}"
            texts_to_embed.append(text_for_embed)
            items.append(CatalogItem(
                canonical_name=row['canonical_name'],
                category=row['category'],
                synonyms=synonyms,
                non_payable=row['non_payable'] == '1',
                non_payable_reason=row['non_payable_reason'] or None,
                bundled_in=row['bundled_in'] or None,
                max_per_day=int(row['max_per_day']) if row['max_per_day'] else None,
                ref_price_low=float(row['ref_price_low']) if row['ref_price_low'] else None,
                ref_price_high=float(row['ref_price_high']) if row['ref_price_high'] else None,
                ref_unit=row['ref_unit'] or None,
                ref_source=row['ref_source'] or None
            ))
            
    print(f"Seeding {len(items)} catalog items...")
    embeddings = embedder.embed_passages(texts_to_embed)
    
    for item, emb in zip(items, embeddings):
        item.embedding = emb
        
    session.add_all(items)
    await session.commit()

async def seed_kb(session: AsyncSession):
    res = await session.execute(select(Document).where(Document.kind == 'kb').limit(1))
    if res.scalar() is not None:
        print("KB already seeded.")
        return

    kb_dir = os.path.join(os.path.dirname(__file__), 'kb')
    documents = []
    chunks = []
    texts_to_embed = []
    
    for filename in os.listdir(kb_dir):
        if not filename.endswith('.md'): continue
        filepath = os.path.join(kb_dir, filename)
        
        doc = Document(id=uuid.uuid4(), kind="kb", name=filename, page_count=1)
        documents.append(doc)
        
        with open(filepath, 'r', encoding='utf-8') as f:  # noqa: ASYNC230
            content = f.read()
            
        parts = content.split('## ')
        for i, part in enumerate(parts):
            if not part.strip(): continue
            if i == 0 and 'Demo knowledge base' in part:
                continue # header
            
            lines = part.strip().split('\n')
            heading = lines[0].strip()
            text_body = '\n'.join(lines[1:]).strip()
            
            if not text_body: continue
            
            chunk = Chunk(
                document_id=doc.id,
                page=1,
                heading=heading,
                text=text_body
            )
            chunks.append(chunk)
            texts_to_embed.append(text_body)

    print(f"Seeding {len(documents)} KB docs with {len(chunks)} chunks...")
    embeddings = embedder.embed_passages(texts_to_embed)
    
    for chunk, emb in zip(chunks, embeddings):
        chunk.embedding = emb
        
    session.add_all(documents)
    session.add_all(chunks)
    await session.commit()

async def main():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    async with AsyncSessionLocal() as session:
        await seed_catalog(session)
        await seed_kb(session)
    print("Seed complete.")

if __name__ == '__main__':
    asyncio.run(main())
