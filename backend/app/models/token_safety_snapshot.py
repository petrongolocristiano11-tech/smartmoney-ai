from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    JSON,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class TokenSafetySnapshot(Base):
    __tablename__ = "token_safety_snapshots"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    token_mint: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
    )

    liquidity_usd: Mapped[float] = mapped_column(Float, default=0.0)
    market_cap_usd: Mapped[float] = mapped_column(Float, default=0.0)
    volume_24h_usd: Mapped[float] = mapped_column(Float, default=0.0)
    top_holder_percent: Mapped[float] = mapped_column(Float, default=100.0)
    risk_score: Mapped[int] = mapped_column(Integer, default=100)

    honeypot: Mapped[bool] = mapped_column(Boolean, default=True)
    mint_authority_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    freeze_authority_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    rugged: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    rugcheck_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    source: Mapped[str] = mapped_column(String(120), default="ONCHAIN+DEXSCREENER+JUPITER")
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
