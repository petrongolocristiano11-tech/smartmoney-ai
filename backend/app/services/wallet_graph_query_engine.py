from backend.app.models.wallet_edge import WalletEdge


def get_wallet_graph(db, wallet_address: str):
    edges = (
        db.query(WalletEdge)
        .filter(
            (WalletEdge.source_wallet == wallet_address)
            | (WalletEdge.target_wallet == wallet_address)
        )
        .all()
    )

    return {
        "wallet": wallet_address,
        "connections": len(edges),
        "edges": [
            {
                "source": edge.source_wallet,
                "target": edge.target_wallet,
                "token": edge.token_mint,
                "strength": edge.strength,
                "type": edge.edge_type,
            }
            for edge in edges
        ],
    } 