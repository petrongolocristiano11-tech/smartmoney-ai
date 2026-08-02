from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.database.session import SessionLocal
from backend.app.services.gen4_evidence_sprint_service import (
    GEN4_EVIDENCE_SPRINT_CONFIRMATION,
    preview_gen4_evidence_sprint,
    run_gen4_evidence_sprint,
)


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Tipo non serializzabile: {type(value)!r}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--priority-wallet", required=True)
    parser.add_argument("--lookback-days", type=int, default=45)
    parser.add_argument("--max-token-discovery-requests", type=int, default=3)
    parser.add_argument("--max-candidate-probes", type=int, default=8)
    parser.add_argument("--max-companions", type=int, default=1)
    parser.add_argument("--max-backfill-requests-per-wallet", type=int, default=15)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--output", required=True)
    return parser


def main() -> None:
    args = _parser().parse_args()
    evaluated_at = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        common = {
            "priority_wallet": args.priority_wallet,
            "lookback_days": args.lookback_days,
            "max_token_discovery_requests": args.max_token_discovery_requests,
            "max_candidate_probes": args.max_candidate_probes,
            "max_companions": args.max_companions,
            "max_backfill_requests_per_wallet": args.max_backfill_requests_per_wallet,
            "page_size": args.page_size,
            "evaluated_at": evaluated_at,
        }
        if args.execute:
            report = run_gen4_evidence_sprint(
                db,
                confirmation=args.confirmation,
                **common,
            )
        else:
            report = preview_gen4_evidence_sprint(db, **common)
    finally:
        db.close()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=_json_default),
        encoding="utf-8",
    )

    if not args.execute:
        print("PIANO M49-M50 READ-ONLY")
        print(f"Wallet prioritario: {report['priority_wallet']}")
        print(
            "Storico prioritario: "
            f"{report['priority_wallet_stats']['history_span_days']} giorni"
        )
        print(f"Token seed: {len(report['seed_tokens'])}")
        print(
            "Budget Helius massimo: "
            f"{report['parameters']['maximum_total_helius_requests']}"
        )
        print(f"Conferma richiesta: {GEN4_EVIDENCE_SPRINT_CONFIRMATION}")
        print(f"Report: {output}")
        print("Nessuna richiesta esterna e nessuna scrittura eseguita.")
        return

    summary = report["summary"]
    profitability = report["gen4_profitability"]
    proxy = profitability["proxy_metrics"]
    baseline = profitability["baseline_metrics"]
    print("SPRINT M49-M50 COMPLETATO")
    print(f"Richieste Helius: {summary['helius_requests']}")
    print(f"Compagni selezionati: {summary['companions_selected']}")
    print(f"Compagni con almeno 21 giorni: {summary['companions_with_21_days']}")
    print(f"Trade importati: {summary['trades_imported']}")
    for item in report["backfill_results"]:
        print(
            f"- {item['wallet_address']} | status={item['status']} | "
            f"stop={item['stop_reason']} | richieste={item['helius_requests']} | "
            f"span={item['after']['history_span_days']} giorni"
        )
    print(f"Verdetto M47: {summary['m47_verdict']}")
    print(f"Stato economico: {summary['economic_result_status']}")
    print(
        "SIGNAL_ONLY_PROXY: "
        f"chiusi={proxy['closed_trades']} "
        f"return={proxy['total_return_percent']}% "
        f"PF={proxy['profit_factor']} "
        f"drawdown={proxy['max_drawdown_percent']}%"
    )
    print(
        "SIMPLE_COPY_BASELINE: "
        f"chiusi={baseline['closed_trades']} "
        f"return={baseline['total_return_percent']}% "
        f"PF={baseline['profit_factor']} "
        f"drawdown={baseline['max_drawdown_percent']}%"
    )
    print(
        "Gate training: "
        + json.dumps(
            report["diagnostic"]["training_gate_reason_counts"],
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    print(f"Report: {output}")
    print(
        "STRICT_GEN4 non ricostruita retroattivamente; nessuna promozione, "
        "paper order o attivazione LIVE."
    )


if __name__ == "__main__":
    main()
