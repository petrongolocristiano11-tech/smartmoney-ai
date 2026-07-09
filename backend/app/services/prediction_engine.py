from collections import defaultdict

from backend.app.models.trade import Trade


def calculate_wallet_prediction(db, wallet_address: str):
    trades = (
        db.query(Trade)
        .filter(Trade.wallet_address == wallet_address)
        .all()
    )

    if not trades:
        return {
            "wallet": wallet_address,
            "tokens_analyzed": 0,
            "successful_tokens": 0,
            "prediction_score": 0,
        }

    tokens = defaultdict(list)

    for trade in trades:
        tokens[trade.token_mint].append(trade)

    successful = 0

    for token_trades in tokens.values():

        buy_sol = sum(
            t.sol_amount
            for t in token_trades
            if t.side == "BUY"
        )

        sell_sol = sum(
            t.sol_amount
            for t in token_trades
            if t.side == "SELL"
        )

        if sell_sol > buy_sol:
            successful += 1

    prediction_score = (
        successful / len(tokens)
    ) * 100

    return {
        "wallet": wallet_address,
        "tokens_analyzed": len(tokens),
        "successful_tokens": successful,
        "prediction_score": round(prediction_score, 2),
    } 