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
        timeout=20,
    )

    response.raise_for_status()
    return response.json()


def get_solana_health():
    return solana_rpc_call("getHealth")


def get_wallet_balance(address: str):
    response = solana_rpc_call("getBalance", [address])
    lamports = response["result"]["value"]

    return {
        "address": address,
        "lamports": lamports,
        "sol": lamports / 1_000_000_000,
    }


def get_wallet_transactions(address: str, limit: int = 10):
    response = solana_rpc_call(
        "getSignaturesForAddress",
        [
            address,
            {
                "limit": limit,
            },
        ],
    )

    return response["result"]


def get_transaction_detail(signature: str):
    response = solana_rpc_call(
        "getTransaction",
        [
            signature,
            {
                "encoding": "jsonParsed",
                "maxSupportedTransactionVersion": 0,
            },
        ],
    )

    return response["result"]


def analyze_wallet(address: str):
    transactions = get_wallet_transactions(address, limit=10)

    analyzed = []

    for tx in transactions:
        analyzed.append(
            {
                "signature": tx["signature"],
                "slot": tx["slot"],
                "status": tx["confirmationStatus"],
                "success": tx["err"] is None,
                "block_time": tx["blockTime"],
            }
        )

    return {
        "wallet": address,
        "transactions_found": len(analyzed),
        "transactions": analyzed,
    }


def classify_transaction(signature: str):
    tx_detail = get_transaction_detail(signature)

    if tx_detail is None:
        return {
            "signature": signature,
            "type": "unknown",
            "programs": [],
            "success": False,
        }

    instructions = tx_detail["transaction"]["message"]["instructions"]

    programs = []

    for instruction in instructions:
        program = instruction.get("program", "unknown")
        programs.append(program)

    if "vote" in programs:
        tx_type = "vote"
    elif "system" in programs:
        tx_type = "system_transfer"
    elif "spl-token" in programs:
        tx_type = "token_operation"
    else:
        tx_type = "unknown"

    return {
        "signature": signature,
        "type": tx_type,
        "programs": programs,
        "success": tx_detail["meta"]["err"] is None,
        "slot": tx_detail["slot"],
        "block_time": tx_detail["blockTime"],
    } 