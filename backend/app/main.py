from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from backend.app.api.discovered_wallets import (
    router as discovered_wallets_router,
)
from backend.app.api.helius import router as helius_router
from backend.app.api.live import router as live_router
from backend.app.api.scanner import router as scanner_router
from backend.app.api.solana import router as solana_router
from backend.app.api.tokens import router as tokens_router
from backend.app.api.trades import router as trades_router
from backend.app.api.wallets import router as wallet_router
from backend.app.database.session import engine


app = FastAPI(
    title="SmartMoney AI",
    version="0.8.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(live_router)
app.include_router(tokens_router)
app.include_router(scanner_router)
app.include_router(wallet_router)
app.include_router(solana_router)
app.include_router(helius_router)
app.include_router(trades_router)
app.include_router(discovered_wallets_router)


@app.get("/")
def home():
    return {
        "status": "online",
        "project": "SmartMoney AI",
        "version": "0.8.0",
    }


@app.get("/health")
def health():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))

    return {
        "status": "ok",
        "database": "connected",
    } 