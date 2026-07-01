import httpx

from backend.app.core.config import settings


def solana_rpc_call(method: str, params: list | None = None):
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or [],
    }

    response = httpx.post(
        settings.SOLANA_RPC_URL,
        json=payload,
        timeout=10,
    )

    response.raise_for_status()
    return response.json()


def get_solana_health():
    return solana_rpc_call("getHealth") 