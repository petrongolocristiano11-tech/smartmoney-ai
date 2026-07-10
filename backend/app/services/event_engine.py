from datetime import datetime


def build_event(
    event_type: str,
    payload: dict,
):
    return {
        "type": event_type,
        "timestamp": datetime.utcnow().isoformat(),
        "payload": payload,
    }


def wallet_buy_event(
    wallet: str,
    token: str,
    amount: float,
):
    return build_event(
        "WALLET_BUY",
        {
            "wallet": wallet,
            "token": token,
            "amount": amount,
        },
    )


def wallet_sell_event(
    wallet: str,
    token: str,
    amount: float,
):
    return build_event(
        "WALLET_SELL",
        {
            "wallet": wallet,
            "token": token,
            "amount": amount,
        },
    ) 