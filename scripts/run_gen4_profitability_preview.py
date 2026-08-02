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
from backend.app.services.blockchain_parser_gen4_profitability_service import (
    preview_gen4_profitability,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--training-days", type=int, default=None)
    parser.add_argument("--test-days", type=int, default=None)
    parser.add_argument("--step-days", type=int, default=None)
    parser.add_argument("--max-windows", type=int, default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with SessionLocal() as db:
        report = preview_gen4_profitability(
            db,
            training_days=args.training_days,
            test_days=args.test_days,
            step_days=args.step_days,
            max_windows=args.max_windows,
            evaluated_at=datetime.now(timezone.utc),
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    strict = report["strict_metrics"]
    proxy = report["proxy_metrics"]
    baseline = report["baseline_metrics"]
    print(f"Verdetto M47: {report['verdict']}")
    print(f"Stato evidenza strict: {report['strict_evidence_status']}")
    print(
        "STRICT_GEN4: "
        f"trade chiusi={strict['closed_trades']}, "
        f"return={strict['total_return_percent']}%, "
        f"PF={strict['profit_factor']}, "
        f"drawdown={strict['max_drawdown_percent']}%"
    )
    print(
        "SIGNAL_ONLY_PROXY: "
        f"trade chiusi={proxy['closed_trades']}, "
        f"return={proxy['total_return_percent']}%, "
        f"PF={proxy['profit_factor']}, "
        f"drawdown={proxy['max_drawdown_percent']}%"
    )
    print(
        "SIMPLE_COPY_BASELINE: "
        f"trade chiusi={baseline['closed_trades']}, "
        f"return={baseline['total_return_percent']}%, "
        f"PF={baseline['profit_factor']}, "
        f"drawdown={baseline['max_drawdown_percent']}%"
    )
    print(f"Gap evidenza: {', '.join(report['evidence_gaps']) or 'nessuno'}")
    print(f"Report: {args.output}")
    print("Preview read-only: nessuna riga M47 persistita e nessuna attivazione LIVE.")


if __name__ == "__main__":
    main()
