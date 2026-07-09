from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class WalletEdge(Base):
    __tablename__ = "wallet_edges"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    source_wallet: Mapped[str] = mapped_column(String(64), index=True)
    target_wallet: Mapped[str] = mapped_column(String(64), index=True)

    token_mint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    edge_type: Mapped[str] = mapped_column(String(30), default="SHARED_TOKEN")
    strength: Mapped[float] = mapped_column(Float, default=0)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    ) 