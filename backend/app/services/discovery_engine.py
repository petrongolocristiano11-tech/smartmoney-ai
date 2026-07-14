from sqlalchemy.orm import Session

from backend.app.models.trade import Trade
from backend.app.services.discovered_wallet_service import (
    save_discovered_wallet,
)
from backend.app.services.helius import (
    get_wallet_history,
)
from backend.app.services.profile_engine import (
    build_wallet_profile,
)
from backend.app.services.wallet_sync_service import (
    sync_wallet,
)


def get_traded_tokens_by_wallet(
    db: Session,
    wallet_address: str,
):
    rows = (
        db.query(Trade.token_mint)
        .filter(
            Trade.wallet_address
            == wallet_address
        )
        .filter(
            Trade.token_mint.isnot(None)
        )
        .distinct()
        .all()
    )

    tokens = [
        row[0]
        for row in rows
        if row[0]
    ]

    return {
        "wallet": wallet_address,
        "tokens_found": len(tokens),
        "tokens": tokens,
    }


def get_wallets_by_token(
    db: Session,
    token_mint: str,
):
    rows = (
        db.query(Trade.wallet_address)
        .filter(
            Trade.token_mint == token_mint
        )
        .distinct()
        .all()
    )

    wallets = [
        row[0]
        for row in rows
        if row[0]
    ]

    return {
        "token_mint": token_mint,
        "wallets_found": len(wallets),
        "wallets": wallets,
    }


def discover_wallets_from_token_onchain(
    token_mint: str,
):
    transactions = get_wallet_history(
        token_mint
    )

    wallets = set()

    for transaction in transactions:
        if transaction.get("type") != "SWAP":
            continue

        fee_payer = transaction.get(
            "feePayer"
        )

        if fee_payer:
            wallets.add(fee_payer)

    return {
        "token_mint": token_mint,
        "wallets_found": len(wallets),
        "wallets": list(wallets),
    }


def discover_import_and_score_wallets_from_token(
    db: Session,
    token_mint: str,
    limit: int = 10,
):
    discovery = (
        discover_wallets_from_token_onchain(
            token_mint
        )
    )

    results = []

    for wallet_address in discovery[
        "wallets"
    ][:limit]:
        score = sync_wallet(
            db,
            wallet_address,
        )

        analytics = score["dna"][
            "analytics"
        ]

        profile = build_wallet_profile(
            db=db,
            wallet_address=wallet_address,
        )

        save_discovered_wallet(
            db=db,
            wallet_address=wallet_address,
            discovered_from_token=token_mint,
            smart_score=profile[
                "smart_score"
            ],
            roi_percent=analytics[
                "total_roi_percent"
            ],
            win_rate_percent=analytics[
                "win_rate_percent"
            ],
            profit_loss_sol=analytics[
                "total_profit_loss_sol"
            ],
            reliable_positions=analytics[
                "reliable_positions"
            ],
        )

        results.append(profile)

    results.sort(
        key=lambda item: item[
            "smart_score"
        ],
        reverse=True,
    )

    return {
        "token_mint": token_mint,
        "wallets_discovered": discovery[
            "wallets_found"
        ],
        "wallets_analyzed": len(results),
        "ranking": results,
    }


def discover_full_from_wallet(
    db: Session,
    wallet_address: str,
    max_tokens: int = 5,
    max_wallets_per_token: int = 5,
):
    # Prima importa gli swap del seed wallet.
    seed_score = sync_wallet(
        db,
        wallet_address,
    )

    seed_analytics = seed_score["dna"][
        "analytics"
    ]

    seed_trades = int(
        seed_analytics.get(
            "total_trades",
            0,
        )
    )

    # Salva il profilo del seed solo se
    # sono stati importati dati reali.
    if seed_trades > 0:
        build_wallet_profile(
            db=db,
            wallet_address=wallet_address,
        )

    # Ora i token vengono letti dopo
    # l'importazione dei trade.
    token_data = (
        get_traded_tokens_by_wallet(
            db,
            wallet_address,
        )
    )

    tokens = token_data["tokens"][
        :max_tokens
    ]

    discovered_wallets = set()

    for token_mint in tokens:
        discovery = (
            discover_wallets_from_token_onchain(
                token_mint
            )
        )

        for discovered_wallet in discovery[
            "wallets"
        ][:max_wallets_per_token]:
            if (
                discovered_wallet
                and discovered_wallet
                != wallet_address
            ):
                discovered_wallets.add(
                    discovered_wallet
                )

    results = []

    for discovered_wallet in discovered_wallets:
        score = sync_wallet(
            db,
            discovered_wallet,
        )

        analytics = score["dna"][
            "analytics"
        ]

        profile = build_wallet_profile(
            db=db,
            wallet_address=(
                discovered_wallet
            ),
        )

        save_discovered_wallet(
            db=db,
            wallet_address=(
                discovered_wallet
            ),
            discovered_from_token=(
                "MULTI_TOKEN"
            ),
            smart_score=profile[
                "smart_score"
            ],
            roi_percent=analytics[
                "total_roi_percent"
            ],
            win_rate_percent=analytics[
                "win_rate_percent"
            ],
            profit_loss_sol=analytics[
                "total_profit_loss_sol"
            ],
            reliable_positions=analytics[
                "reliable_positions"
            ],
        )

        results.append(profile)

    results.sort(
        key=lambda item: item[
            "smart_score"
        ],
        reverse=True,
    )

    return {
        "seed_wallet": wallet_address,
        "seed_trades_imported": seed_trades,
        "seed_tokens_found": token_data[
            "tokens_found"
        ],
        "tokens_processed": len(tokens),
        "wallets_discovered": len(
            discovered_wallets
        ),
        "ranking": results,
    } 