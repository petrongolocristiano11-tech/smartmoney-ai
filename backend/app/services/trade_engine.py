def normalize_swap(swap: dict):
    token_transfers = swap.get("tokenTransfers", [])
    native_transfers = swap.get("nativeTransfers", [])

    return {
        "signature": swap.get("signature"),
        "timestamp": swap.get("timestamp"),
        "source": swap.get("source"),
        "fee": swap.get("fee"),
        "fee_payer": swap.get("feePayer"),
        "transaction_error": swap.get("transactionError"),
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


def identify_swap_side(normalized_swap: dict):
    wallet = normalized_swap.get("fee_payer")
    token_transfers = normalized_swap["token_transfers"]

    sol_mint = "So11111111111111111111111111111111111111112"

    sent_sol = False
    received_sol = False

    for transfer in token_transfers:
        mint = transfer.get("mint")
        from_wallet = transfer.get("fromUserAccount")
        to_wallet = transfer.get("toUserAccount")

        if mint != sol_mint:
            continue

        if from_wallet == wallet:
            sent_sol = True

        if to_wallet == wallet:
            received_sol = True

    if sent_sol:
        side = "BUY"
    elif received_sol:
        side = "SELL"
    else:
        side = "UNKNOWN"

    return side


def extract_trade_amounts(normalized_swap: dict):
    wallet = normalized_swap.get("fee_payer")
    token_transfers = normalized_swap["token_transfers"]

    sol_mint = "So11111111111111111111111111111111111111112"

    token_mint = None
    token_amount = None
    sol_amount = None

    for transfer in token_transfers:
        mint = transfer.get("mint")
        amount = transfer.get("tokenAmount")
        from_wallet = transfer.get("fromUserAccount")
        to_wallet = transfer.get("toUserAccount")

        if mint == sol_mint and (from_wallet == wallet or to_wallet == wallet):
            sol_amount = amount

        if mint != sol_mint and (from_wallet == wallet or to_wallet == wallet):
            token_mint = mint
            token_amount = amount

    return {
        "token_mint": token_mint,
        "token_amount": token_amount,
        "sol_amount": sol_amount,
    }


def summarize_swap(normalized_swap: dict):
    tokens = extract_swap_tokens(normalized_swap)

    return {
        "signature": normalized_swap["signature"],
        "timestamp": normalized_swap["timestamp"],
        "source": normalized_swap["source"],
        "fee_payer": normalized_swap["fee_payer"],
        "token_count": len(tokens),
        "tokens": tokens,
    }


def build_trade(normalized_swap: dict):
    summary = summarize_swap(normalized_swap)
    side = identify_swap_side(normalized_swap)
    amounts = extract_trade_amounts(normalized_swap)

    return {
        "signature": summary["signature"],
        "timestamp": summary["timestamp"],
        "source": summary["source"],
        "fee_payer": summary["fee_payer"],
        "side": side,
        "tokens": summary["tokens"],
        "token_count": summary["token_count"],
        "token_mint": amounts["token_mint"],
        "token_amount": amounts["token_amount"],
        "sol_amount": amounts["sol_amount"],
        "fee": normalized_swap["fee"],
    }


def build_trade_data(wallet: str, trade: dict):
    return {
        "signature": trade["signature"],
        "wallet_address": wallet,
        "side": trade["side"],
        "source": trade["source"],
        "token_mint": trade["token_mint"],
        "token_amount": trade["token_amount"],
        "sol_amount": trade["sol_amount"],
        "fee": trade["fee"],
        "success": True,
        "block_time": None,
        "raw_json": str(trade),
    } 