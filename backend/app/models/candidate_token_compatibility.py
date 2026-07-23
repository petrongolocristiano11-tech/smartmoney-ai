from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class CandidateTokenCompatibility(Base):
    __tablename__ = "candidate_token_compatibilities"
    __table_args__ = (
        UniqueConstraint(
            "token_mint",
            "fixed_buy_size_lamports",
            "slippage_bps",
            name="uq_candidate_token_compatibility_quote_profile",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    token_mint: Mapped[str] = mapped_column(String(64), index=True)
    fixed_buy_size_lamports: Mapped[int] = mapped_column(BigInteger)
    slippage_bps: Mapped[int] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(String(24), default="FAILED", index=True)
    buy_quote: Mapped[bool] = mapped_column(Boolean, default=False)
    sell_quote: Mapped[bool] = mapped_column(Boolean, default=False)
    compatible: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    buy_out_amount_raw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sell_out_amount_raw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
