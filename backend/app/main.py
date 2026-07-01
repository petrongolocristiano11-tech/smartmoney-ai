from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.database.session import engine, get_db
from backend.app.models.wallet import Wallet
from backend.app.schemas.wallet import WalletCreate, WalletResponse
from backend.app.services.solana_rpc import (
    get_solana_health,
    get_wallet_balance,
    get_wallet_transactions,
)

app = FastAPI(
    title="SmartMoney AI",
    version="0.5.0",
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
    new_wallet = Wallet(address=wallet.address)

    db.add(new_wallet)
    db.commit()
    db.refresh(new_wallet)

    return {
        "id": new_wallet.id,
        "address": new_wallet.address,
        "message": "Wallet creato con successo",
    }


@app.get("/wallets", response_model=list[WalletResponse])
def get_wallets(
    db: Session = Depends(get_db),
):
    return db.query(Wallet).all()


@app.get("/wallets/{wallet_id}", response_model=WalletResponse | None)
def get_wallet(
    wallet_id: int,
    db: Session = Depends(get_db),
):
    return db.query(Wallet).filter(Wallet.id == wallet_id).first()


@app.delete("/wallets/{wallet_id}")
def delete_wallet(
    wallet_id: int,
    db: Session = Depends(get_db),
):
    wallet = db.query(Wallet).filter(Wallet.id == wallet_id).first()

    if wallet is None:
        return {
            "message": "Wallet non trovato",
        }

    db.delete(wallet)
    db.commit()

    return {
        "message": "Wallet eliminato con successo",
        "id": wallet_id,
    }


@app.get("/solana/health")
def solana_health():
    return get_solana_health()


@app.get("/solana/balance/{address}")
def solana_balance(address: str):
    return get_wallet_balance(address)


@app.get("/solana/transactions/{address}")
def solana_transactions(address: str):
    return get_wallet_transactions(address) 