import ast

from backend.app.models.discovered_wallet import DiscoveredWallet
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


def calculate_wallet_influence(
    db,
    wallet_address: str,
    max_followers: int = 20,
):
    wallet_buys = (
        db.query(Trade)
        .filter(Trade.wallet_address == wallet_address)
        .filter(Trade.side == "BUY")
        .filter(Trade.token_mint.isnot(None))
        .all()
    )

    if not wallet_buys:
        return {
            "wallet": wallet_address,
            "tokens_analyzed": 0,
            "followers_detected": 0,
            "influence_score": 0,
            "top_followers": [],
        }

    token_first_buy = {}

    for trade in wallet_buys:
        timestamp = get_trade_timestamp(trade)

        if trade.token_mint not in token_first_buy:
            token_first_buy[trade.token_mint] = timestamp
        else:
            token_first_buy[trade.token_mint] = min(
                token_first_buy[trade.token_mint],
                timestamp,
            )

    followers = {}

    for token_mint, leader_timestamp in token_first_buy.items():
        later_buys = (
            db.query(Trade)
            .filter(Trade.token_mint == token_mint)
            .filter(Trade.side == "BUY")
            .filter(Trade.wallet_address != wallet_address)
            .all()
        )

        for trade in later_buys:
            follower_timestamp = get_trade_timestamp(trade)

            if follower_timestamp <= leader_timestamp:
                continue

            if trade.wallet_address not in followers:
                followers[trade.wallet_address] = {
                    "shared_tokens_after": 0,
                    "tokens": set(),
                }

            followers[trade.wallet_address]["shared_tokens_after"] += 1
            followers[trade.wallet_address]["tokens"].add(token_mint)

    results = []

    for follower_wallet, data in followers.items():
        discovered = (
            db.query(DiscoveredWallet)
            .filter(DiscoveredWallet.wallet_address == follower_wallet)
            .first()
        )

        smart_score = discovered.smart_score if discovered else 0
        roi_percent = discovered.roi_percent if discovered else 0
        win_rate_percent = discovered.win_rate_percent if discovered else 0

        follower_strength = (
            data["shared_tokens_after"] * 10
            + smart_score * 0.5
        )

        results.append(
            {
                "wallet": follower_wallet,
                "shared_tokens_after": data["shared_tokens_after"],
                "smart_score": smart_score,
                "roi_percent": roi_percent,
                "win_rate_percent": win_rate_percent,
                "follower_strength": round(follower_strength, 2),
            }
        )

    results.sort(
        key=lambda item: item["follower_strength"],
        reverse=True,
    )

    followers_detected = len(results)
    tokens_analyzed = len(token_first_buy)

    influence_score = min(
        100,
        followers_detected * 3
        + sum(item["follower_strength"] for item in results[:5]) * 0.2,
    )

    return {
        "wallet": wallet_address,
        "tokens_analyzed": tokens_analyzed,
        "followers_detected": followers_detected,
        "influence_score": round(influence_score, 2),
        "top_followers": results[:max_followers],
    } 