from sqlalchemy import Column
from sqlalchemy import Float
from sqlalchemy import Integer
from sqlalchemy import String

from backend.app.database.session import Base


class WalletProfile(Base):

    __tablename__ = "wallet_profiles"

    id = Column(Integer, primary_key=True)

    wallet_address = Column(
        String,
        unique=True,
        index=True,
    )

    smart_score = Column(Float)

    roi = Column(Float)

    win_rate = Column(Float)

    profit = Column(Float)

    activity = Column(Integer)

    influence_score = Column(Float)

    conviction_score = Column(Float)

    early_buyer_score = Column(Float)

    prediction_score = Column(Float)

    dna = Column(String)

    risk = Column(String)

    version = Column(String) 