"""
SQLite database connection and ORM models for PolicyPilotAI.

Tables:
    claims      — every claim submitted via POST /decide
    decisions   — AI-generated coverage decision for each claim
    audit_log   — lightweight audit trail (ingest, decide, errors)

Usage (FastAPI dependency injection):
    async def my_route(db: AsyncSession = Depends(get_db)): ...
"""
from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship

from app.config import settings

# ── Engine & session factory ────────────────────────────────────────────────────

engine = create_async_engine(settings.DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


# ── Base ────────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


# ── ORM Models ──────────────────────────────────────────────────────────────────

class Claim(Base):
    """One row per claim submitted by a claimant or adjuster."""
    __tablename__ = "claims"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    claimant_name  = Column(String(120), nullable=True)
    policy_number  = Column(String(50),  nullable=True)
    claim_type     = Column(String(30),  nullable=False)
    incident_date  = Column(String(20),  nullable=True)
    claim_amount   = Column(Float,       nullable=True)
    description    = Column(Text,        nullable=False)
    created_at     = Column(DateTime,    server_default=func.now())

    decision = relationship("Decision", back_populates="claim", uselist=False)


class Decision(Base):
    """One row per AI coverage decision, linked 1-to-1 with a Claim."""
    __tablename__ = "decisions"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    claim_id         = Column(Integer, ForeignKey("claims.id"), nullable=False, unique=True)
    decision         = Column(String(30), nullable=False)
    confidence       = Column(Float,      nullable=False)
    reasoning        = Column(Text,       nullable=False)
    relevant_clauses = Column(Text,       nullable=False, default="[]")  # JSON list
    exclusions_noted = Column(Text,       nullable=False, default="[]")  # JSON list
    recommendation   = Column(Text,       nullable=False, default="")
    model_used       = Column(String(80), nullable=False)
    created_at       = Column(DateTime,   server_default=func.now())

    claim = relationship("Claim", back_populates="decision")


class AuditLog(Base):
    """Lightweight event log — ingestion triggers, errors, etc."""
    __tablename__ = "audit_log"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    event      = Column(String(80), nullable=False)
    detail     = Column(Text,       nullable=True)
    created_at = Column(DateTime,   server_default=func.now())


# ── FastAPI dependency ──────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session per request."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """Create all tables if they do not yet exist (called on app startup)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
