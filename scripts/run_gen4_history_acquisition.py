from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.database.session import SessionLocal
from backend.app.services.gen4_history_acquisition_service import (
    GEN4_HISTORY_ACQUISITION_CONFIRMATION,
    preview_gen4_history_acquisition,
    run_gen4_history_acquisition,
)


def _write_report(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--wallet", action="append", default=[])
    parser.add_argument("--lookback-days", type=int, default=45)
    parser.add_argument("--max-wallets", type=int, default=2)
    parser.add_argument("--max-helius-requests-per-wallet", type=int, default=10)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    evaluated_at = datetime.now(timezone.utc)
    with SessionLocal() as db:
        if args.execute:
            report = run_gen4_history_acquisition(
                db,
                confirmation=args.confirmation,
                wallet_addresses=args.wallet,
                lookback_days=args.lookback_days,
                max_wallets=args.max_wallets,
                max_helius_requests_per_wallet=(
                    args.max_helius_requests_per_wallet
                ),
                page_size=args.page_size,
                evaluated_at=evaluated_at,
            )
        else:
            report = preview_gen4_history_acquisition(
                db,
                wallet_addresses=args.wallet,
                lookback_days=args.lookback_days,
                max_wallets=args.max_wallets,
                max_helius_requests_per_wallet=(
                    args.max_helius_requests_per_wallet
                ),
                page_size=args.page_size,
                evaluated_at=evaluated_at,
            )

    _write_report(args.output, report)

    if not args.execute:
        print("PIANO M48 READ-ONLY")
        print(f"Wallet selezionati: {report['selected_wallet_count']}")
        for row in report["selected_wallets"]:
            print(
                f"- {row['wallet_address']} | "
                f"selezione={row['selection_reason']} | "
                f"qualita={row['quality_classification']} | "
                f"promozione={row['promotion_status']} | "
                f"trade={row['trade_count']} | "
                f"span={row['history_span_days']} giorni"
            )
        for row in report["rejected_requested_wallets"]:
            print(
                f"- RIFIUTATO {row['wallet_address']} | "
                f"motivo={row['reason']}"
            )
        print(
            "Budget Helius massimo: "
            f"{report['parameters']['maximum_total_helius_requests']}"
        )
        print(f"Conferma richiesta: {GEN4_HISTORY_ACQUISITION_CONFIRMATION}")
        print(f"Report: {args.output}")
        print("Nessuna richiesta esterna e nessuna scrittura eseguita.")
        return

    summary = report["summary"]
    profitability = report["gen4_profitability_after_acquisition"]
    strict = profitability["strict_metrics"]
    proxy = profitability["proxy_metrics"]
    baseline = profitability["baseline_metrics"]
    print("ACQUISIZIONE M48 COMPLETATA")
    print(f"Wallet tentati: {summary['wallets_attempted']}")
    print(f"Richieste Helius: {summary['helius_requests']}")
    print(f"Trade importati: {summary['trades_imported']}")
    print(f"Trade aggiornati: {summary['trades_updated']}")
    for row in report["wallet_results"]:
        print(
            f"- {row['wallet_address']} | status={row['status']} | "
            f"stop={row['stop_reason']} | richieste={row['helius_requests']} | "
            f"span={row['after']['history_span_days']} giorni"
        )
    print(f"Verdetto M47 dopo M48: {profitability['verdict']}")
    print(
        "STRICT_GEN4: "
        f"chiusi={strict['closed_trades']} return={strict['total_return_percent']}% "
        f"PF={strict['profit_factor']} drawdown={strict['max_drawdown_percent']}%"
    )
    print(
        "SIGNAL_ONLY_PROXY: "
        f"chiusi={proxy['closed_trades']} return={proxy['total_return_percent']}% "
        f"PF={proxy['profit_factor']} drawdown={proxy['max_drawdown_percent']}%"
    )
    print(
        "SIMPLE_COPY_BASELINE: "
        f"chiusi={baseline['closed_trades']} return={baseline['total_return_percent']}% "
        f"PF={baseline['profit_factor']} drawdown={baseline['max_drawdown_percent']}%"
    )
    print(f"Gap evidenza: {', '.join(profitability['evidence_gaps']) or 'nessuno'}")
    print(f"Report: {args.output}")
    print(
        "Acquisizione evidence-only: nessun ricalcolo qualità, "
        "nessuna promozione, nessun paper order e nessuna attivazione LIVE."
    )


if __name__ == "__main__":
    main()
