from sqlalchemy.orm import Session

from backend.app.models.wallet_edge import WalletEdge


def save_wallet_edge(
    db: Session,
    source_wallet: str,
    target_wallet: str,
    token_mint: str | None = None,
    edge_type: str = "SHARED_TOKEN",
    strength: float = 0,
):
    existing = (
        db.query(WalletEdge)
        .filter(WalletEdge.source_wallet == source_wallet)
        .filter(WalletEdge.target_wallet == target_wallet)
        .filter(WalletEdge.token_mint == token_mint)
        .first()
    )

    if existing:
        existing.strength = max(existing.strength, strength)
        db.commit()
        return existing

    edge = WalletEdge(
        source_wallet=source_wallet,
        target_wallet=target_wallet,
        token_mint=token_mint,
        edge_type=edge_type,
        strength=strength,
    )

    db.add(edge)
    db.commit()
    db.refresh(edge)

    return edge
