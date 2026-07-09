from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class WalletProfile(Base):
    __tablename__ = "wallet_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    wallet_address: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
    )

    smart_score: Mapped[float] = mapped_column(Float, default=0)
    roi: Mapped[float] = mapped_column(Float, default=0)
    win_rate: Mapped[float] = mapped_column(Float, default=0)
    profit: Mapped[float] = mapped_column(Float, default=0)
    activity: Mapped[int] = mapped_column(Integer, default=0)

    influence_score: Mapped[float] = mapped_column(Float, default=0)
    conviction_score: Mapped[float] = mapped_column(Float, default=0)
    early_buyer_score: Mapped[float] = mapped_column(Float, default=0)
    prediction_score: Mapped[float] = mapped_column(Float, default=0)
    holding_score: Mapped[float] = mapped_column(Float, default=0)

    classification: Mapped[str] = mapped_column(String(50), default="NORMAL")
    traits: Mapped[str] = mapped_column(Text, default="NORMAL")

    dna: Mapped[str] = mapped_column(String(50), default="NORMAL")
    risk: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    version: Mapped[str] = mapped_column(String(20), default="3.0")

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    ) 