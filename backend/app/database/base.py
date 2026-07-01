from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import dei modelli per permettere ad Alembic di rilevarli
from backend.app.models import Wallet
