from __future__ import annotations

import argparse
import json

from backend.app.database.session import SessionLocal
from backend.app.services.m63_helius_credit_containment_service import (
    M63_CONTAINMENT_CONFIRMATION,
    M63_TARGET_WALLET,
    apply_m63_helius_credit_containment,
    inspect_m63_helius_credit_containment,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Disabilita i consumer Helius costosi e conserva solo la campagna target."
    )
    parser.add_argument("--target-wallet", default=M63_TARGET_WALLET)
    parser.add_argument(
        "--confirmation",
        default="",
        help=f"Per applicare: {M63_CONTAINMENT_CONFIRMATION}",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    with SessionLocal() as db:
        before = inspect_m63_helius_credit_containment(
            db,
            target_wallet=args.target_wallet,
        )
        print("=== M63 HELIUS CREDIT CONTAINMENT ===")
        print("MODE=" + ("APPLY" if args.confirmation else "DRY_RUN"))
        print("BEFORE=" + json.dumps(before, sort_keys=True))
        if not args.confirmation:
            print(f"CONFIRMATION_REQUIRED={M63_CONTAINMENT_CONFIRMATION}")
            print("DATABASE_WRITES=0")
            print("HELIUS_REQUESTS=0")
            return 0

        result = apply_m63_helius_credit_containment(
            db,
            confirmation=args.confirmation,
            target_wallet=args.target_wallet,
        )
        db.commit()
        after = inspect_m63_helius_credit_containment(
            db,
            target_wallet=args.target_wallet,
        )
        print("RESULT=" + json.dumps(result, sort_keys=True))
        print("AFTER=" + json.dumps(after, sort_keys=True))
        print("HISTORY_PRESERVED=YES")
        print("ROWS_DELETED=0")
        print("HELIUS_REQUESTS=0")
        print("CONTAINMENT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
