from collections import defaultdict
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


def calculate_wallet_holding_time(db, wallet_address: str):
    trades = (
        db.query(Trade)
        .filter(Trade.wallet_address == wallet_address)
        .filter(Trade.token_mint.isnot(None))
        .all()
    )

    grouped = defaultdict(list)

    for trade in trades:
        grouped[trade.token_mint].append(trade)

    holding_hours = []

    for token_trades in grouped.values():
        buys = [t for t in token_trades if t.side == "BUY"]
        sells = [t for t in token_trades if t.side == "SELL"]

        if not buys or not sells:
            continue

        first_buy = min(get_trade_timestamp(t) for t in buys)
        last_sell = max(get_trade_timestamp(t) for t in sells)

        if first_buy > 0 and last_sell > first_buy:
            holding_hours.append((last_sell - first_buy) / 3600)

    if not holding_hours:
        return {
            "wallet": wallet_address,
            "positions_analyzed": 0,
            "average_holding_hours": 0,
            "holding_score": 0,
            "style": "UNKNOWN",
        }

    average_holding_hours = sum(holding_hours) / len(holding_hours)

    if average_holding_hours < 1:
        style = "SCALPER"
        holding_score = 40
    elif average_holding_hours < 24:
        style = "INTRADAY"
        holding_score = 70
    elif average_holding_hours < 168:
        style = "SWING"
        holding_score = 90
    else:
        style = "HOLDER"
        holding_score = 80

    return {
        "wallet": wallet_address,
        "positions_analyzed": len(holding_hours),
        "average_holding_hours": round(average_holding_hours, 2),
        "holding_score": holding_score,
        "style": style,
    } 