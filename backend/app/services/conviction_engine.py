from collections import defaultdict

from backend.app.models.trade import Trade


def calculate_wallet_conviction(db, wallet_address: str):
    trades = (
        db.query(Trade)
        .filter(Trade.wallet_address == wallet_address)
        .all()
    )

    if not trades:
        return {
            "wallet": wallet_address,
            "tokens_analyzed": 0,
            "average_buy_size": 0,
            "average_position_size": 0,
            "conviction_score": 0,
        }

    tokens = defaultdict(list)

    for trade in trades:
        tokens[trade.token_mint].append(trade)

    buy_sizes = []
    position_sizes = []

    for token_trades in tokens.values():

        buy_sol = sum(
            t.sol_amount
            for t in token_trades
            if t.side == "BUY"
        )

        if buy_sol > 0:
            buy_sizes.append(buy_sol)

        position_sizes.append(buy_sol)

    average_buy = (
        sum(buy_sizes) / len(buy_sizes)
        if buy_sizes
        else 0
    )

    average_position = (
        sum(position_sizes) / len(position_sizes)
        if position_sizes
        else 0
    )

    conviction_score = min(
        average_position * 40,
        100,
    )

    return {
        "wallet": wallet_address,
        "tokens_analyzed": len(tokens),
        "average_buy_size": round(average_buy, 4),
        "average_position_size": round(average_position, 4),
        "conviction_score": round(conviction_score, 2),
    } 