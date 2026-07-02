from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    signature: Mapped[str] = mapped_column(String(128), unique=True, index=True)

    wallet_address: Mapped[str] = mapped_column(String(64), index=True)

    side: Mapped[str] = mapped_column(String(20), default="UNKNOWN")

    source: Mapped[str | None] = mapped_column(String(50), nullable=True)

    token_mint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    token_amount: Mapped[float | None] = mapped_column(Float, nullable=True)

    sol_amount: Mapped[float | None] = mapped_column(Float, nullable=True)

    fee: Mapped[float | None] = mapped_column(Float, nullable=True)

    success: Mapped[bool] = mapped_column(Boolean, default=True)

    block_time: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    ) 