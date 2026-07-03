from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class DiscoveryJob(Base):
    __tablename__ = "discovery_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    status: Mapped[str] = mapped_column(
        String(20),
        default="PENDING",
    )

    seed_wallet: Mapped[str] = mapped_column(
        String(64),
    )

    wallets_found: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    wallets_processed: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    ) 