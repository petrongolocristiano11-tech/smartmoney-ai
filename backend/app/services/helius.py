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


def get_enhanced_transaction(signature: str):
    url = f"https://api.helius.xyz/v0/transactions/?api-key={settings.HELIUS_API_KEY}"

    response = httpx.post(
        url,
        json={"transactions": [signature]},
        timeout=20,
    )

    response.raise_for_status()
    return response.json()


def get_wallet_history(address: str):
    url = (
        f"https://api.helius.xyz/v0/addresses/"
        f"{address}/transactions"
        f"?api-key={settings.HELIUS_API_KEY}"
    )

    response = httpx.get(url, timeout=20)

    response.raise_for_status()
    return response.json()


def normalize_swap(swap: dict):
    token_transfers = swap.get("tokenTransfers", [])
    native_transfers = swap.get("nativeTransfers", [])

    return {
        "signature": swap.get("signature"),
        "timestamp": swap.get("timestamp"),
        "source": swap.get("source"),
        "fee": swap.get("fee"),
        "type": swap.get("type"),
        "description": swap.get("description"),

        "token_transfers": token_transfers,
        "native_transfers": native_transfers,

        "token_transfer_count": len(token_transfers),
        "native_transfer_count": len(native_transfers),
    } 
def extract_swap_tokens(normalized_swap: dict):
    tokens = []

    for transfer in normalized_swap["token_transfers"]:
        tokens.append(
            {
                "mint": transfer.get("mint"),
                "amount": transfer.get("tokenAmount"),
                "from": transfer.get("fromUserAccount"),
                "to": transfer.get("toUserAccount"),
            }
        )

    return tokens 
def summarize_swap(normalized_swap: dict):
    tokens = extract_swap_tokens(normalized_swap)

    return {
        "signature": normalized_swap["signature"],
        "timestamp": normalized_swap["timestamp"],
        "source": normalized_swap["source"],
        "token_count": len(tokens),
        "tokens": tokens,
    } 
def identify_swap_side(normalized_swap: dict):
    token_transfers = normalized_swap["token_transfers"]
    native_transfers = normalized_swap["native_transfers"]

    side = "UNKNOWN"

    if native_transfers:
        first_transfer = native_transfers[0]
        amount = first_transfer.get("amount", 0)

        if amount < 0:
            side = "BUY"
        elif amount > 0:
            side = "SELL"

    return {
        "side": side,
        "token_transfers": token_transfers,
        "native_transfers": native_transfers,
    } 
def build_trade(normalized_swap: dict):
    summary = summarize_swap(normalized_swap)
    side = identify_swap_side(normalized_swap)

    return {
        "signature": summary["signature"],
        "timestamp": summary["timestamp"],
        "source": summary["source"],
        "side": side["side"],
        "tokens": summary["tokens"],
        "token_count": summary["token_count"],
    } 

def get_wallet_swaps(address: str):
    transactions = get_wallet_history(address)

    swaps = [
        normalize_swap(tx)
        for tx in transactions
        if tx.get("type") == "SWAP"
    ]

    return {
        "wallet": address,
        "swaps_found": len(swaps),
        "swaps": swaps,
    } 