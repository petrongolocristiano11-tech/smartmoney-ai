from fastapi import FastAPI
from sqlalchemy import text

from backend.app.database.session import engine

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