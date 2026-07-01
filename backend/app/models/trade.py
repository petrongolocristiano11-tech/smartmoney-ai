from sqlalchemy import DateTime, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    wallet_id: Mapped[int] = mapped_column(
        ForeignKey("wallets.id"),
        index=True,
    )

    token_id: Mapped[int] = mapped_column(
        ForeignKey("tokens.id"),
        index=True,
    )

    amount: Mapped[float] = mapped_column(Float)

    price: Mapped[float] = mapped_column(Float)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    