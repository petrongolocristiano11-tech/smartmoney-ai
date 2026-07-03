from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class DiscoveredWallet(Base):
    __tablename__ = "discovered_wallets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    wallet_address: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    discovered_from_token: Mapped[str | None] = mapped_column(String(64), nullable=True)

    smart_score: Mapped[float] = mapped_column(Float, default=0)

    roi_percent: Mapped[float] = mapped_column(Float, default=0)

    win_rate_percent: Mapped[float] = mapped_column(Float, default=0)

    profit_loss_sol: Mapped[float] = mapped_column(Float, default=0)

    reliable_positions: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[str] = mapped_column(String(20), default="DISCOVERED")

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    ) 