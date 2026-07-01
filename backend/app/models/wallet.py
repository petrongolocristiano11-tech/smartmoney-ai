from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.sql import func

from backend.app.database.base import Base
from sqlalchemy.orm import Mapped, mapped_column


class Wallet(Base):
    __tablename__ = "wallets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    address: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    smart_score: Mapped[float] = mapped_column(Float, default=0)

    win_rate: Mapped[float] = mapped_column(Float, default=0)

    roi: Mapped[float] = mapped_column(Float, default=0)

    total_profit: Mapped[float] = mapped_column(Float, default=0)

    active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    