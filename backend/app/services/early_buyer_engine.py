import ast

from backend.app.models.trade import Trade


def get_trade_timestamp(trade):
    if trade.block_time:
        return trade.block_time.timestamp()

    if trade.raw_json:
        try:
            data = ast.literal_eval(trade.raw_json)
            return data.get("timestamp") or 0
        except Exception:
            return 0

    return 0


def calculate_early_buyer_score(
    db,
    wallet_address: str,
    early_rank_threshold: int = 10,
):
    wallet_tokens = (
        db.query(Trade.token_mint)
        .filter(Trade.wallet_address == wallet_address)
        .filter(Trade.token_mint.isnot(None))
        .distinct()
        .all()
    )

    tokens = [row[0] for row in wallet_tokens]

    early_entries = 0
    analyzed_tokens = 0
    ranks = []

    for token_mint in tokens:
        buy_trades = (
            db.query(Trade)
            .filter(Trade.token_mint == token_mint)
            .filter(Trade.side == "BUY")
            .all()
        )

        if not buy_trades:
            continue

        first_buy_by_wallet = {}

        for trade in buy_trades:
            timestamp = get_trade_timestamp(trade)

            if trade.wallet_address not in first_buy_by_wallet:
                first_buy_by_wallet[trade.wallet_address] = timestamp
            else:
                first_buy_by_wallet[trade.wallet_address] = min(
                    first_buy_by_wallet[trade.wallet_address],
                    timestamp,
                )

        ordered_wallets = sorted(
            first_buy_by_wallet.items(),
            key=lambda item: item[1],
        )

        analyzed_tokens += 1

        for rank, (buyer_wallet, _) in enumerate(ordered_wallets, start=1):
            if buyer_wallet == wallet_address:
                ranks.append(rank)

                if rank <= early_rank_threshold:
                    early_entries += 1

                break

    early_buyer_score = (
        (early_entries / analyzed_tokens) * 100
        if analyzed_tokens > 0
        else 0
    )

    average_entry_rank = (
        sum(ranks) / len(ranks)
        if ranks
        else 0
    )

    return {
        "wallet": wallet_address,
        "tokens_analyzed": analyzed_tokens,
        "early_entries": early_entries,
        "early_rank_threshold": early_rank_threshold,
        "early_buyer_score": round(early_buyer_score, 2),
        "average_entry_rank": round(average_entry_rank, 2),
        "best_entry_rank": min(ranks) if ranks else 0,
        "worst_entry_rank": max(ranks) if ranks else 0,
    } 