from backend.app.models.trade import Trade


def create_trade(db, trade_data: dict):
    trade = Trade(**trade_data)

    db.add(trade)
    db.commit()
    db.refresh(trade)

    return trade


def trade_exists(db, signature: str):
    return (
        db.query(Trade)
        .filter(Trade.signature == signature)
        .first()
    )


def create_trade_if_not_exists(db, trade_data: dict):
    existing_trade = trade_exists(db, trade_data["signature"])

    if existing_trade:
        for key, value in trade_data.items():
            setattr(existing_trade, key, value)

        db.commit()
        db.refresh(existing_trade)

        return existing_trade

    return create_trade(db, trade_data) 