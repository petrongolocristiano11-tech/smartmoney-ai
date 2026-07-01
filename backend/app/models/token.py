from sqlalchemy import DateTime, Integer, String
from sqlalchemy.sql import func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.database.base import Base


class Token(Base):
    __tablename__ = "tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    address: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    symbol: Mapped[str] = mapped_column(String(20))

    name: Mapped[str] = mapped_column(String(100))

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    