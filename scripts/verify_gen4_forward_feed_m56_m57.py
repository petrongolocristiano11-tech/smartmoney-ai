from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def structural_checks() -> None:
    files = {
        "model": PROJECT_ROOT / "backend/app/models/gen4_forward_feed.py",
        "service": PROJECT_ROOT / "backend/app/services/blockchain_parser_gen4_forward_feed_service.py",
        "worker": PROJECT_ROOT / "backend/app/workers/gen4_forward_feed_worker.py",
        "runtime": PROJECT_ROOT / "backend/app/services/gen4_forward_feed_runtime.py",
        "migration": PROJECT_ROOT / "alembic/versions/a5e7c1d4b926_add_gen4_forward_feed.py",
        "panel": PROJECT_ROOT / "frontend/src/components/gen4Forward/Gen4ForwardFeedPanel.jsx",
        "page": PROJECT_ROOT / "frontend/src/pages/Gen4Forward.jsx",
        "api": PROJECT_ROOT / "frontend/src/services/gen4ForwardApi.js",
    }
    for label, path in files.items():
        if not path.exists():
            raise RuntimeError(f"File M56-M57 mancante ({label}): {path}")
    service = files["service"].read_text(encoding="utf-8")
    main = (PROJECT_ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    config = (PROJECT_ROOT / "backend/app/core/config.py").read_text(encoding="utf-8")
    page = files["page"].read_text(encoding="utf-8")
    assert "GEN4_FORWARD_FEED_POLICY_VERSION" in service
    assert "historical_backfill_before_anchor_allowed\": False" in service
    assert "/integrity/parser-gen4-forward/feed/status" in main
    assert "/integrity/parser-gen4-forward/feed/poll" in main
    assert "CANONICAL_PARSER_GEN4_FORWARD_FEED_DAILY_REQUEST_CAP" in config
    assert "Gen4ForwardFeedPanel" in page
    assert "Acquisisci ora" in page
    print("GEN4_FORWARD_FEED_STRUCTURE=OK")
    print("FEED_POLICY=canonical-parser-gen4-forward-feed/1")
    print("SAFETY=FROZEN_WALLETS_ONLY_POINT_IN_TIME_NO_PAPER_NO_LIVE")


def database_checks() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import inspect

    from backend.app.core.config import settings
    from backend.app.database.session import SessionLocal, engine
    from backend.app.services.blockchain_parser_gen4_forward_feed_service import (
        get_gen4_forward_feed_status,
    )

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["a5e7c1d4b926"]
    tables = set(inspect(engine).get_table_names())
    assert "canonical_parser_gen4_forward_feed_states" in tables
    assert "canonical_parser_gen4_forward_feed_runs" in tables
    with SessionLocal() as db:
        status = get_gen4_forward_feed_status(db)
        db.commit()
    print("GEN4_FORWARD_FEED_DATABASE=OK")
    print(f"GEN4_FORWARD_FEED_ENABLED={bool(settings.CANONICAL_PARSER_GEN4_FORWARD_FEED_ENABLED)}")
    print(f"GEN4_FORWARD_FEED_AUTOSTART={bool(settings.CANONICAL_PARSER_GEN4_FORWARD_FEED_AUTOSTART)}")
    print(f"ACTIVE_CAMPAIGN_ID={status['campaign_id']}")
    print(f"FROZEN_WALLETS={len(status['frozen_wallets'])}")
    print(f"INTERVAL_SECONDS={status['state']['interval_seconds']}")
    print(f"DAILY_REQUEST_CAP={status['state']['daily_request_cap']}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--structure-only", action="store_true")
    args = parser.parse_args()
    structural_checks()
    if args.structure_only:
        print("DATABASE_CHECK=SKIPPED")
        return 0
    database_checks()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
