from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.database.session import SessionLocal
from backend.app.services.blockchain_parser_gen4_forward_feed_service import (
    GEN4_FORWARD_FEED_CONFIGURE_CONFIRMATION,
    GEN4_FORWARD_FEED_POLL_CONFIRMATION,
    configure_gen4_forward_feed,
    get_gen4_forward_feed_status,
    run_gen4_forward_feed_poll,
)


def _json_default(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["status", "configure", "poll"])
    parser.add_argument("--campaign-id")
    parser.add_argument("--enabled", choices=["true", "false"], default="true")
    parser.add_argument("--interval-seconds", type=int, default=120)
    parser.add_argument("--max-requests", type=int, default=4)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--overlap-seconds", type=int, default=90)
    parser.add_argument("--report")
    args = parser.parse_args()

    with SessionLocal() as db:
        status = get_gen4_forward_feed_status(db)
        campaign_id = args.campaign_id or status["campaign_id"]
        if args.action == "status":
            result = status
        elif args.action == "configure":
            result = configure_gen4_forward_feed(
                db,
                campaign_id=campaign_id,
                confirmation=GEN4_FORWARD_FEED_CONFIGURE_CONFIRMATION,
                enabled=args.enabled == "true",
                interval_seconds=args.interval_seconds,
                max_requests_per_run=args.max_requests,
                page_size=args.page_size,
                overlap_seconds=args.overlap_seconds,
            )
            db.commit()
        else:
            result = run_gen4_forward_feed_poll(
                db,
                campaign_id=campaign_id,
                confirmation=GEN4_FORWARD_FEED_POLL_CONFIRMATION,
                trigger="MANUAL",
            )
            db.commit()

    if args.report:
        report = Path(args.report).expanduser().resolve()
    else:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        report = Path.home() / "Downloads" / f"smartmoney-gen4-forward-feed-{args.action}-{stamp}.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    print("GEN4_FORWARD_FEED_ACTION_COMPLETED")
    print(f"ACTION={args.action}")
    if isinstance(result, dict) and isinstance(result.get("run"), dict):
        run = result["run"]
        print(f"RUN_STATUS={run.get('status')}")
        print(f"HELIUS_REQUESTS={run.get('helius_requests')}")
        print(f"TRADES_IMPORTED={run.get('trades_imported')}")
        print(f"NEW_DECISIONS={run.get('new_decisions')}")
    state = result.get("state") if isinstance(result, dict) else None
    if state is None and isinstance(result, dict):
        state = (result.get("status") or {}).get("state")
    if isinstance(state, dict):
        print(f"FEED_ENABLED={state.get('enabled')}")
        print(f"TOTAL_HELIUS_REQUESTS={state.get('total_helius_requests')}")
        print(f"TOTAL_TRADES_IMPORTED={state.get('total_trades_imported')}")
    print(f"REPORT={report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
