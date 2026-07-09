from heapq import heappop, heappush

from backend.app.services.discovery_engine import (
    discover_wallets_from_token_onchain,
    get_traded_tokens_by_wallet,
)
from backend.app.services.profile_engine import build_wallet_profile
from backend.app.services.wallet_graph_engine import save_wallet_edge
from backend.app.services.wallet_sync_service import sync_wallet


def smart_discovery_from_wallet(
    db,
    seed_wallet: str,
    max_depth: int = 2,
    max_tokens_per_wallet: int = 5,
    max_wallets_per_token: int = 5,
    min_smart_score: float = 60,
):
    queue = []
    heappush(queue, (-100, 0, seed_wallet))

    visited = set()
    smart_wallets = []

    while queue:
        _, depth, wallet = heappop(queue)

        if wallet in visited:
            continue

        visited.add(wallet)

        try:
            sync_wallet(db, wallet)
            profile = build_wallet_profile(db, wallet)
        except Exception:
            continue

        smart_score = profile["smart_score"]

        if smart_score >= min_smart_score:
            smart_wallets.append(profile)

        if depth >= max_depth:
            continue

        if wallet != seed_wallet and smart_score < min_smart_score:
            continue

        token_data = get_traded_tokens_by_wallet(db, wallet)

        for token in token_data["tokens"][:max_tokens_per_wallet]:
            try:
                discovery = discover_wallets_from_token_onchain(token)
            except Exception:
                continue

            for discovered_wallet in discovery["wallets"][:max_wallets_per_token]:
                if discovered_wallet == wallet:
                    continue

                save_wallet_edge(
                    db=db,
                    source_wallet=wallet,
                    target_wallet=discovered_wallet,
                    token_mint=token,
                    strength=smart_score,
                )

                if discovered_wallet not in visited:
                    heappush(
                        queue,
                        (-smart_score, depth + 1, discovered_wallet),
                    )

    smart_wallets.sort(
        key=lambda item: item["smart_score"],
        reverse=True,
    )

    return {
        "seed_wallet": seed_wallet,
        "max_depth": max_depth,
        "wallets_analyzed": len(visited),
        "smart_wallets_found": len(smart_wallets),
        "min_smart_score": min_smart_score,
        "ranking": smart_wallets,
    } 