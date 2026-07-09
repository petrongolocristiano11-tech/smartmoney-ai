from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.app.models.wallet_edge import WalletEdge


def ensure_wallet_edges_table(db: Session):
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS wallet_edges (
                id SERIAL PRIMARY KEY,
                source_wallet VARCHAR(64),
                target_wallet VARCHAR(64),
                token_mint VARCHAR(64),
                edge_type VARCHAR(30) DEFAULT 'SHARED_TOKEN',
                strength FLOAT DEFAULT 0,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    )

    db.commit()


def save_wallet_edge(
    db: Session,
    source_wallet: str,
    target_wallet: str,
    token_mint: str | None = None,
    edge_type: str = "SHARED_TOKEN",
    strength: float = 0,
):
    ensure_wallet_edges_table(db)

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