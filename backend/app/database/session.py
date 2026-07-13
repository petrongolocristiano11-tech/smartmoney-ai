from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import (
    Session,
    sessionmaker,
)

from backend.app.core.config import settings


engine = create_engine(
    settings.DATABASE_URL,
    echo=settings.SQL_ECHO,
    pool_pre_ping=True,
    pool_recycle=(
        settings.DB_POOL_RECYCLE_SECONDS
    ),
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[
    Session,
    None,
    None,
]:
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close() 