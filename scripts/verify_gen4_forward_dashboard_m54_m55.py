from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verifica dashboard Gen4 Forward M54-M55."
    )
    parser.add_argument(
        "--structure-only",
        action="store_true",
        help="Verifica file e patch frontend senza importare runtime o database.",
    )
    args = parser.parse_args(argv)

    required = [
        "frontend/src/pages/Gen4Forward.jsx",
        "frontend/src/services/gen4ForwardApi.js",
        "frontend/src/components/gen4Forward/Gen4ForwardEquityChart.jsx",
        "frontend/src/components/gen4Forward/Gen4ForwardTables.jsx",
    ]
    for relative in required:
        if not (PROJECT_ROOT / relative).is_file():
            raise RuntimeError(f"File dashboard mancante: {relative}")

    main_jsx = (PROJECT_ROOT / "frontend/src/main.jsx").read_text(
        encoding="utf-8-sig"
    )
    navbar = (PROJECT_ROOT / "frontend/src/components/Navbar.jsx").read_text(
        encoding="utf-8-sig"
    )
    assert 'path="/gen4-forward"' in main_jsx
    assert 'path: "/gen4-forward"' in navbar

    print("GEN4_FORWARD_DASHBOARD_STRUCTURE=OK")
    print("DASHBOARD_ROUTE=/gen4-forward")

    if args.structure_only:
        print("DATABASE_CHECK=SKIPPED")
        return 0

    from backend.app.database.session import SessionLocal
    from backend.app.services.blockchain_parser_gen4_forward_shadow_service import (
        get_gen4_forward_status,
    )

    with SessionLocal() as db:
        status = get_gen4_forward_status(db)

    campaign = status.get("latest_campaign") or {}
    if not status.get("active_campaign_id"):
        raise RuntimeError("Campagna Gen4 forward attiva non trovata.")
    if campaign.get("status") != "ACTIVE":
        raise RuntimeError(
            f"Stato campagna inatteso: {campaign.get('status')}"
        )
    if int(campaign.get("frozen_wallet_count") or 0) < 2:
        raise RuntimeError("Wallet congelati insufficienti.")

    print("GEN4_FORWARD_DASHBOARD_CONTRACT=OK")
    print(f"GEN4_ENABLED={status.get('enabled')}")
    print(f"ACTIVE_CAMPAIGN_ID={status.get('active_campaign_id')}")
    print(f"CAMPAIGN_STATUS={campaign.get('status')}")
    print(f"VERDICT={campaign.get('verdict')}")
    print(f"FROZEN_WALLETS={campaign.get('frozen_wallet_count', 0)}")
    print(f"CYCLES={campaign.get('cycle_count', 0)}")
    print(f"STRICT_CLOSED={campaign.get('strict_closed_trade_count', 0)}")
    print("SAFETY=READ_ONLY_PLUS_MANUAL_SHADOW_CYCLE_NO_PAPER_NO_LIVE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
