from backend.app.models.trade import Trade


def get_traded_tokens_by_wallet(db, wallet_address: str):
    rows = (
        db.query(Trade.token_mint)
        .filter(Trade.wallet_address == wallet_address)
        .filter(Trade.token_mint.isnot(None))
        .distinct()
        .all()
    )

    tokens = [row[0] for row in rows]

    return {
        "wallet": wallet_address,
        "tokens_found": len(tokens),
        "tokens": tokens,
    } 
    
def get_wallets_by_token(db, token_mint: str):
    rows = (
        db.query(Trade.wallet_address)
        .filter(Trade.token_mint == token_mint)
        .distinct()
        .all()
    )

    wallets = [row[0] for row in rows]

    return {
        "token_mint": token_mint,
        "wallets_found": len(wallets),
        "wallets": wallets,
    } 