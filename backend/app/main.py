from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.database.session import engine, get_db
from backend.app.models.wallet import Wallet
from backend.app.schemas.wallet import WalletCreate

app = FastAPI(
    title="SmartMoney AI",
    version="0.2.0",
)


@app.get("/")
def home():
    return {
        "status": "online",
        "project": "SmartMoney AI",
    }


@app.get("/health")
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    return {
        "status": "ok",
        "database": "connected",
    }


@app.post("/wallets")
def create_wallet(
    wallet: WalletCreate,
    db: Session = Depends(get_db),
):
    new_wallet = Wallet(
        address=wallet.address,
    )

    db.add(new_wallet)
    db.commit()
    db.refresh(new_wallet)

    return {
        "id": new_wallet.id,
        "address": new_wallet.address,
        "message": "Wallet creato con successo",
    }
    