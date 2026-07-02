from backend.app.models.trade import Trade


def build_wallet_portfolio(db, wallet_address: str):
    trades = (
        db.query(Trade)
        .filter(Trade.wallet_address == wallet_address)
        .all()
    )

    portfolio = {}

    for trade in trades:
        if trade.token_mint is None:
            continue

        if trade.token_mint not in portfolio:
            portfolio[trade.token_mint] = {
                "token_mint": trade.token_mint,
                "bought_amount": 0,
                "sold_amount": 0,
                "holding_amount": 0,
                "buy_trades": 0,
                "sell_trades": 0,
                "total_sol_spent": 0,
                "total_sol_received": 0,
            }

        position = portfolio[trade.token_mint]

        if trade.side == "BUY":
            position["bought_amount"] += trade.token_amount or 0
            position["holding_amount"] += trade.token_amount or 0
            position["buy_trades"] += 1
            position["total_sol_spent"] += trade.sol_amount or 0

        elif trade.side == "SELL":
            position["sold_amount"] += trade.token_amount or 0
            position["holding_amount"] -= trade.token_amount or 0
            position["sell_trades"] += 1
            position["total_sol_received"] += trade.sol_amount or 0

    return {
        "wallet": wallet_address,
        "tokens_count": len(portfolio),
        "positions": list(portfolio.values()),
    } 