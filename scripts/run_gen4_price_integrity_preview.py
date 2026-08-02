from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.constants import GEN4_MANDATORY_EXCLUDED_PRICE_MINTS
from backend.app.database.session import SessionLocal
from backend.app.services.blockchain_parser_gen4_profitability_service import (
    LANE_BASELINE,
    LANE_PROXY,
    LANE_STRICT,
    preview_gen4_profitability,
)


def _all_outcomes(report: dict[str, Any]):
    for window in report["windows"]:
        for lane, rows in window["trades"].items():
            for row in rows:
                yield window["sequence"], lane, row


def _validate(report: dict[str, Any]) -> dict[str, Any]:
    policy = report["policy_snapshot"]
    excluded = set(policy["excluded_price_mints"])
    mandatory = set(GEN4_MANDATORY_EXCLUDED_PRICE_MINTS)
    if not mandatory <= excluded:
        raise AssertionError("Quote asset obbligatori non completamente esclusi")

    maximum_ratio = float(policy["maximum_price_discontinuity_ratio"])
    maximum_return = (maximum_ratio - 1.0) * 100.0 + 1.0
    quote_asset_outcomes: list[dict[str, Any]] = []
    extreme_outcomes: list[dict[str, Any]] = []
    threshold_violations: list[dict[str, Any]] = []
    closed_rows: list[dict[str, Any]] = []

    for sequence, lane, row in _all_outcomes(report):
        enriched = {"window": sequence, "lane": lane, **row}
        if row["token_mint"] in excluded:
            quote_asset_outcomes.append(enriched)
        value = row.get("return_percent")
        if value is not None:
            closed_rows.append(enriched)
            if abs(float(value)) > maximum_return:
                extreme_outcomes.append(enriched)
        if row.get("exit_reason") == "TAKE_PROFIT" and value is not None:
            if float(value) > float(policy["take_profit_percent"]) + 0.05:
                threshold_violations.append(enriched)
        if row.get("exit_reason") == "STOP_LOSS" and value is not None:
            if float(value) < -float(policy["stop_loss_percent"]) - 5.0:
                threshold_violations.append(enriched)

    if quote_asset_outcomes:
        raise AssertionError(
            f"Quote asset presenti negli outcome: {len(quote_asset_outcomes)}"
        )
    if extreme_outcomes:
        raise AssertionError(
            f"Outcome oltre il rapporto massimo: {len(extreme_outcomes)}"
        )
    if threshold_violations:
        raise AssertionError(
            f"Fill TP/SL oltre la soglia: {len(threshold_violations)}"
        )

    return {
        "quote_asset_outcome_count": len(quote_asset_outcomes),
        "extreme_outcome_count": len(extreme_outcomes),
        "threshold_violation_count": len(threshold_violations),
        "closed_outcome_count": len(closed_rows),
        "maximum_allowed_absolute_return_percent": round(maximum_return, 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with SessionLocal() as db:
        report = preview_gen4_profitability(
            db,
            evaluated_at=datetime.now(timezone.utc),
        )

    validation = _validate(report)
    report["m51_price_integrity_validation"] = validation
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    audit = report["summary"]["price_integrity_audit"]
    strict = report["strict_metrics"]
    proxy = report["proxy_metrics"]
    baseline = report["baseline_metrics"]

    print("RICALCOLO GEN4 M51 COMPLETATO")
    print(f"Verdetto: {report['verdict']}")
    print(f"Policy: {report['policy_version']}")
    print(
        "Price audit: "
        f"quote esclusi={audit['excluded_quote_asset_count']}, "
        f"discontinuità scartate={audit['price_discontinuity_rejected_count']}, "
        f"punti validi={audit['accepted_price_point_count']}"
    )
    print(
        "STRICT_GEN4: "
        f"chiusi={strict['closed_trades']} "
        f"return={strict['total_return_percent']}% "
        f"PF={strict['profit_factor']} "
        f"DD={strict['max_drawdown_percent']}%"
    )
    print(
        "SIGNAL_ONLY_PROXY: "
        f"chiusi={proxy['closed_trades']} "
        f"return={proxy['total_return_percent']}% "
        f"PF={proxy['profit_factor']} "
        f"DD={proxy['max_drawdown_percent']}%"
    )
    print(
        "SIMPLE_COPY_BASELINE: "
        f"chiusi={baseline['closed_trades']} "
        f"return={baseline['total_return_percent']}% "
        f"PF={baseline['profit_factor']} "
        f"DD={baseline['max_drawdown_percent']}%"
    )

    print("OUTCOME CHIUSI M51")
    count = 0
    for sequence, lane, row in _all_outcomes(report):
        if row.get("return_percent") is None:
            continue
        count += 1
        wallets = ",".join(row.get("contributing_wallets") or [])
        print(
            f"W{sequence} {lane} | token={row['token_mint']} "
            f"return={row['return_percent']}% reason={row['exit_reason']} "
            f"wallets={wallets}"
        )
    if count == 0:
        print("nessun outcome chiuso dopo la pulizia prezzi")

    print(f"Gap evidenza: {', '.join(report['evidence_gaps']) or 'nessuno'}")
    print(f"Report: {args.output}")
    print("Nessun Helius, scrittura DB, promozione, paper o LIVE.")


if __name__ == "__main__":
    main()
