from sqlalchemy import Column, Integer, String, Boolean, Float, ForeignKey, DateTime, JSON, Text, func
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import declarative_base
from pgvector.sqlalchemy import Vector
import uuid

Base = declarative_base()

class CatalogItem(Base):
    __tablename__ = "catalog_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    canonical_name = Column(Text, nullable=False)
    category = Column(Text, nullable=False)
    synonyms = Column(ARRAY(Text), nullable=True)
    non_payable = Column(Boolean, nullable=True)
    non_payable_reason = Column(Text, nullable=True)
    bundled_in = Column(Text, nullable=True)
    max_per_day = Column(Integer, nullable=True)
    ref_price_low = Column(Float, nullable=True)
    ref_price_high = Column(Float, nullable=True)
    ref_unit = Column(Text, nullable=True)
    ref_source = Column(Text, nullable=True)
    embedding = Column(Vector(384), nullable=True)

class Document(Base):
    __tablename__ = "documents"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    session_id = Column(Text, nullable=True)
    page_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=func.now())

class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"))
    page = Column(Integer, nullable=True)
    heading = Column(Text, nullable=True)
    text = Column(Text, nullable=False)
    embedding = Column(Vector(384), nullable=True)

class Policy(Base):
    __tablename__ = "policies"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id"))
    session_id = Column(Text, nullable=True)
    terms = Column(JSONB, nullable=True)
    confirmed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=func.now())

class Bill(Base):
    __tablename__ = "bills"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(Text, nullable=True)
    file_hash = Column(Text, nullable=True)
    filename = Column(Text, nullable=True)
    storage_path = Column(Text, nullable=True)
    page_count = Column(Integer, nullable=True)
    is_insured = Column(Boolean, nullable=True)
    extracted = Column(JSONB, nullable=True)
    verified = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=func.now())

class Run(Base):
    __tablename__ = "runs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(Text, nullable=True)
    kind = Column(Text, nullable=False)
    bill_id = Column(UUID(as_uuid=True), ForeignKey("bills.id"), nullable=True)
    policy_id = Column(UUID(as_uuid=True), ForeignKey("policies.id"), nullable=True)
    status = Column(Text, nullable=True)
    phase = Column(Text, nullable=True)
    mode = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    result = Column(JSONB, nullable=True)
    created_at = Column(DateTime, default=func.now())
    finished_at = Column(DateTime, nullable=True)

class TraceEvent(Base):
    __tablename__ = "trace_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(UUID(as_uuid=True), ForeignKey("runs.id"))
    seq = Column(Integer, nullable=False)
    ts_ms = Column(Integer, nullable=False)
    agent = Column(Text, nullable=False)
    type = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    data = Column(JSONB, nullable=True)

class LlmCache(Base):
    __tablename__ = "llm_cache"
    key = Column(Text, primary_key=True)
    response = Column(JSONB, nullable=False)
    created_at = Column(DateTime, default=func.now())
