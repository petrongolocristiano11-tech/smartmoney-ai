from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.api.helius import router as helius_router 
from backend.app.api.scanner import router as scanner_router 
from backend.app.api.wallets import router as wallet_router 
from backend.app.api.solana import router as solana_router
from backend.app.database.session import engine, get_db
from backend.app.models.wallet import Wallet
from backend.app.schemas.wallet import WalletCreate, WalletResponse
from backend.app.services.solana_rpc import (
    get_solana_health,
    get_wallet_balance,
    get_wallet_transactions,
    get_transaction_detail,
)

app = FastAPI(
    title="SmartMoney AI",
    version="0.6.0",
)

app.include_router(scanner_router) 
app.include_router(wallet_router) 
app.include_router(solana_router)
app.include_router(helius_router)

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

