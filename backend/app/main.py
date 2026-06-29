from fastapi import FastAPI

app = FastAPI(
    title="SmartMoney AI",
    version="0.1.0"
)

@app.get("/")
def home():
    return {
        "status": "online",
        "project": "SmartMoney AI",
        "message": "Backend funzionante 🚀"
    }
    