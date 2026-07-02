import httpx

from backend.app.core.config import settings


def get_helius_rpc_url():
    return f"https://mainnet.helius-rpc.com/?api-key={settings.HELIUS_API_KEY}"


def helius_rpc_call(method: str, params: list | None = None):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or [],
    }

    response = httpx.post(
        get_helius_rpc_url(),
        json=payload,
        timeout=20,
    )

    response.raise_for_status()
    return response.json()


def get_helius_health():
    return helius_rpc_call("getHealth") 