from __future__ import annotations

from heapq import heappop, heappush

from backend.app.services.discovery_engine import (
    analyze_and_save_discovered_wallet,
    discover_wallets_from_token_onchain,
    get_traded_tokens_by_wallet,
)
from backend.app.services.wallet_graph_engine import save_wallet_edge


def smart_discovery_from_wallet(
    db,
    seed_wallet: str,
    max_depth: int = 2,
    max_tokens_per_wallet: int = 5,
    max_wallets_per_token: int = 5,
    min_smart_score: float = 60,
):
    queue: list[tuple[float, int, str, str]] = []
    heappush(queue, (-100.0, 0, seed_wallet, "SMART_SEED"))

    visited: set[str] = set()
    ranked_wallets: list[dict] = []
    analyzed_profiles: list[dict] = []
    failed_wallets = 0

    while queue:
        _, depth, wallet, source = heappop(queue)
        if wallet in visited:
            continue
        visited.add(wallet)

        try:
            profile = analyze_and_save_discovered_wallet(
                db,
                wallet_address=wallet,
                discovered_from_token=source,
            )
        except Exception:
            db.rollback()
            failed_wallets += 1
            continue

        analyzed_profiles.append(profile)

        smart_score = float(profile.get("smart_score") or 0)
        activity_eligible = bool(profile.get("activity_eligible"))
        quality_eligible = bool(profile.get("quality_eligible"))
        quality_classification = str(
            profile.get("quality_classification") or "NON_ANALIZZATO"
        )
        if (
            smart_score >= min_smart_score
            and activity_eligible
            and quality_eligible
        ):
            ranked_wallets.append(profile)

        if depth >= max_depth:
            continue
        if wallet != seed_wallet and (
            smart_score < min_smart_score
            or not activity_eligible
            or quality_classification in {"SOSPETTO", "NON_COPIABILE"}
        ):
            continue

        token_data = get_traded_tokens_by_wallet(db, wallet)
        for token in token_data["tokens"][:max_tokens_per_wallet]:
            discovery = discover_wallets_from_token_onchain(token)
            if discovery.get("status") == "FAILED":
                continue

            for discovered_wallet in discovery.get("wallets", [])[:max_wallets_per_token]:
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
                    priority = float(profile.get("ranking_score") or smart_score)
                    heappush(
                        queue,
                        (-priority, depth + 1, discovered_wallet, token),
                    )

    ranked_wallets.sort(
        key=lambda item: (
            float(item.get("ranking_score") or 0),
            float(item.get("smart_score") or 0),
        ),
        reverse=True,
    )

    activity_breakdown = {
        classification: sum(
            1
            for item in analyzed_profiles
            if item.get("activity_classification") == classification
        )
        for classification in (
            "ATTIVO",
            "POCO_ATTIVO",
            "INATTIVO",
            "IPERATTIVO",
        )
    }

    quality_breakdown = {
        classification: sum(
            1
            for item in analyzed_profiles
            if item.get("quality_classification") == classification
        )
        for classification in (
            "COPIABILE",
            "OSSERVAZIONE",
            "SOSPETTO",
            "NON_COPIABILE",
        )
    }

    return {
        "status": "COMPLETED" if failed_wallets == 0 else "PARTIAL",
        "seed_wallet": seed_wallet,
        "max_depth": max_depth,
        "wallets_analyzed": len(visited) - failed_wallets,
        "wallets_failed": failed_wallets,
        "smart_wallets_found": len(ranked_wallets),
        "wallets_eligible": sum(
            1 for item in ranked_wallets if item.get("eligible")
        ),
        "min_smart_score": min_smart_score,
        "activity_breakdown": activity_breakdown,
        "quality_breakdown": quality_breakdown,
        "ranking": ranked_wallets,
    }
