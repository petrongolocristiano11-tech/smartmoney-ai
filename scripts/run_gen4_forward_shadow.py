from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from sqlalchemy import desc, select  # noqa: E402

from backend.app.database.session import SessionLocal  # noqa: E402
from backend.app.models.gen4_forward_shadow import (  # noqa: E402
    CanonicalParserGen4ForwardCampaign,
)
from backend.app.services.blockchain_parser_gen4_forward_shadow_service import (  # noqa: E402
    GEN4_FORWARD_CYCLE_CONFIRMATION,
    GEN4_FORWARD_START_CONFIRMATION,
    GEN4_FORWARD_STOP_CONFIRMATION,
    CanonicalParserGen4ForwardShadowError,
    get_gen4_forward_campaign,
    get_gen4_forward_status,
    preview_gen4_forward_campaign,
    run_gen4_forward_cycle,
    start_gen4_forward_campaign,
    stop_gen4_forward_campaign,
)


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _wallets(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    result: list[str] = []
    for value in values:
        result.extend(item.strip() for item in value.split(",") if item.strip())
    return sorted(set(result)) or None


def _write_report(payload: dict[str, Any], output: str | None) -> None:
    if not output:
        return
    path = Path(output).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"REPORT={path}")


def _active_campaign_id(db) -> str:
    campaign = db.scalar(
        select(CanonicalParserGen4ForwardCampaign)
        .where(CanonicalParserGen4ForwardCampaign.status == "ACTIVE")
        .order_by(desc(CanonicalParserGen4ForwardCampaign.id))
        .limit(1)
    )
    if campaign is None:
        raise CanonicalParserGen4ForwardShadowError(
            "Nessuna campagna forward attiva.",
            code="GEN4_FORWARD_ACTIVE_CAMPAIGN_NOT_FOUND",
            status_code=404,
        )
    return campaign.campaign_id


def _print_campaign(payload: dict[str, Any]) -> None:
    print(f"CAMPAIGN_ID={payload['campaign_id']}")
    print(f"STATUS={payload['status']}")
    print(f"VERDICT={payload['verdict']}")
    print(f"STRICT_EVIDENCE_STATUS={payload['strict_evidence_status']}")
    print(f"ANCHOR_AT={payload['anchor_at']}")
    print(f"FROZEN_WALLETS={payload['frozen_wallet_count']}")
    for wallet in payload.get("frozen_wallets", []):
        print(f"  WALLET={wallet}")
    print(f"CYCLES={payload['cycle_count']}")
    print(f"STRICT_CLOSED={payload['strict_closed_trade_count']}")
    print(f"PROXY_CLOSED={payload['proxy_closed_trade_count']}")
    print(f"BASELINE_CLOSED={payload['baseline_closed_trade_count']}")
    strict = payload.get("strict_metrics", {})
    proxy = payload.get("proxy_metrics", {})
    baseline = payload.get("baseline_metrics", {})
    print(
        "STRICT_METRICS="
        f"closed={strict.get('closed_trades', 0)} "
        f"return={strict.get('total_return_percent', 0.0)}% "
        f"PF={strict.get('profit_factor')} "
        f"DD={strict.get('max_drawdown_percent', 0.0)}%"
    )
    print(
        "PROXY_METRICS="
        f"closed={proxy.get('closed_trades', 0)} "
        f"return={proxy.get('total_return_percent', 0.0)}% "
        f"PF={proxy.get('profit_factor')} "
        f"DD={proxy.get('max_drawdown_percent', 0.0)}%"
    )
    print(
        "BASELINE_METRICS="
        f"closed={baseline.get('closed_trades', 0)} "
        f"return={baseline.get('total_return_percent', 0.0)}% "
        f"PF={baseline.get('profit_factor')} "
        f"DD={baseline.get('max_drawdown_percent', 0.0)}%"
    )
    print("EVIDENCE_GAPS=" + ",".join(payload.get("evidence_gaps", [])))


def main() -> int:
    parser = argparse.ArgumentParser(description="M52-M53 Gen4 strict forward shadow campaign")
    subparsers = parser.add_subparsers(dest="command", required=True)

    preview = subparsers.add_parser("preview", help="Preview read-only della selezione wallet")
    preview.add_argument("--candidate-wallet", action="append")
    preview.add_argument("--anchor-at")
    preview.add_argument("--output")

    start = subparsers.add_parser("start", help="Avvia la campagna forward")
    start.add_argument("--candidate-wallet", action="append")
    start.add_argument("--anchor-at")
    start.add_argument("--confirmation", default=GEN4_FORWARD_START_CONFIRMATION)
    start.add_argument("--actor-label", default="LOCAL_GEN4_FORWARD_SHADOW")
    start.add_argument("--note")
    start.add_argument("--output")

    cycle = subparsers.add_parser("cycle", help="Esegue un ciclo forward metadata-only")
    cycle.add_argument("--campaign-id")
    cycle.add_argument("--observed-at")
    cycle.add_argument("--confirmation", default=GEN4_FORWARD_CYCLE_CONFIRMATION)
    cycle.add_argument("--output")

    status = subparsers.add_parser("status", help="Mostra lo stato forward")
    status.add_argument("--campaign-id")
    status.add_argument("--decision-limit", type=int, default=100)
    status.add_argument("--output")

    stop = subparsers.add_parser("stop", help="Chiude la campagna forward")
    stop.add_argument("--campaign-id")
    stop.add_argument("--observed-at")
    stop.add_argument("--confirmation", default=GEN4_FORWARD_STOP_CONFIRMATION)
    stop.add_argument("--actor-label", default="LOCAL_GEN4_FORWARD_SHADOW")
    stop.add_argument("--note")
    stop.add_argument("--output")

    args = parser.parse_args()
    with SessionLocal() as db:
        try:
            if args.command == "preview":
                payload = preview_gen4_forward_campaign(
                    db,
                    candidate_wallets=_wallets(args.candidate_wallet),
                    anchor_at=_dt(args.anchor_at),
                )
                training = payload["training_snapshot"]
                print("GEN4_FORWARD_PREVIEW")
                print(f"READY={payload['ready']}")
                print(f"QUALIFIED_WALLETS={training['qualified_wallet_count']}")
                print(f"SELECTED_WALLETS={training['selected_wallet_count']}")
                print(f"INDEPENDENT_CLUSTERS={training['independent_cluster_count']}")
                print("REASON_CODES=" + ",".join(payload["reason_codes"]))
                for wallet in training["selected_wallets"]:
                    metrics = training["selected_wallet_metrics"][wallet]
                    print(
                        f"  WALLET={wallet} closed={metrics['closed_positions']} "
                        f"return={metrics['return_percent']}% PF={metrics['profit_factor']} "
                        f"WR={metrics['win_rate_percent']}% DD={metrics['max_drawdown_percent']}%"
                    )
                _write_report(payload, args.output)
                return 0

            if args.command == "start":
                payload = start_gen4_forward_campaign(
                    db,
                    confirmation=args.confirmation,
                    candidate_wallets=_wallets(args.candidate_wallet),
                    anchor_at=_dt(args.anchor_at),
                    actor_label=args.actor_label,
                    note=args.note,
                )
                db.commit()
                print("GEN4_FORWARD_CAMPAIGN_STARTED")
                _print_campaign(payload)
                _write_report(payload, args.output)
                return 0

            if args.command == "cycle":
                campaign_id = args.campaign_id or _active_campaign_id(db)
                payload = run_gen4_forward_cycle(
                    db,
                    campaign_id=campaign_id,
                    confirmation=args.confirmation,
                    observed_at=_dt(args.observed_at),
                )
                db.commit()
                print("GEN4_FORWARD_CYCLE_COMPLETED")
                print(f"CYCLE_ID={payload['cycle']['cycle_id']}")
                print(f"CYCLE_SEQUENCE={payload['cycle']['sequence']}")
                print(f"CYCLE_STATUS={payload['cycle']['status']}")
                print(f"NEW_DECISIONS={payload['cycle']['new_decision_count']}")
                print(f"UPDATED_DECISIONS={payload['cycle']['updated_decision_count']}")
                _print_campaign(payload["campaign"])
                _write_report(payload, args.output)
                return 0

            if args.command == "status":
                if args.campaign_id:
                    payload = get_gen4_forward_campaign(
                        db,
                        args.campaign_id,
                        decision_limit=args.decision_limit,
                    )
                    print("GEN4_FORWARD_CAMPAIGN_STATUS")
                    _print_campaign(payload)
                else:
                    payload = get_gen4_forward_status(db)
                    print("GEN4_FORWARD_STATUS")
                    print(f"ENABLED={payload['enabled']}")
                    print(f"CAMPAIGNS={payload['campaign_count']}")
                    print(f"CYCLES={payload['cycle_count']}")
                    print(f"DECISIONS={payload['decision_count']}")
                    print(f"ACTIVE_CAMPAIGN_ID={payload['active_campaign_id']}")
                    if payload["latest_campaign"]:
                        _print_campaign(payload["latest_campaign"])
                _write_report(payload, args.output)
                return 0

            campaign_id = args.campaign_id or _active_campaign_id(db)
            payload = stop_gen4_forward_campaign(
                db,
                campaign_id=campaign_id,
                confirmation=args.confirmation,
                observed_at=_dt(args.observed_at),
                actor_label=args.actor_label,
                note=args.note,
            )
            db.commit()
            print("GEN4_FORWARD_CAMPAIGN_STOPPED")
            _print_campaign(payload)
            _write_report(payload, args.output)
            return 0
        except CanonicalParserGen4ForwardShadowError as exception:
            db.rollback()
            print(f"ERROR_CODE={exception.code}", file=sys.stderr)
            print(str(exception), file=sys.stderr)
            return 2
        except Exception:
            db.rollback()
            raise


if __name__ == "__main__":
    raise SystemExit(main())
