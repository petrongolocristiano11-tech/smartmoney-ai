from __future__ import annotations

import argparse
from pathlib import Path


CONFIG_MARKER = "# BEGIN M56-M57 GEN4 FORWARD AUTOMATIC FEED"
SCHEMA_MARKER = "# BEGIN M56-M57 GEN4 FORWARD AUTOMATIC FEED"
MAIN_MARKER = "# BEGIN M56-M57 GEN4 FORWARD AUTOMATIC FEED"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Anchor mancante per {label}")
    return text.replace(old, new, 1)


def patch_config(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if CONFIG_MARKER in text:
        return False
    anchor = "    CANONICAL_PARSER_GEN4_FORWARD_MAX_SAFETY_WAIT_MINUTES: int = Field(default=30, ge=1, le=10080)\n"
    block = anchor + "\n    # BEGIN M56-M57 GEN4 FORWARD AUTOMATIC FEED\n" + '''    # Incremental source acquisition for frozen wallets; no paper/LIVE execution.\n    CANONICAL_PARSER_GEN4_FORWARD_FEED_ENABLED: bool = False\n    CANONICAL_PARSER_GEN4_FORWARD_FEED_AUTOSTART: bool = False\n    CANONICAL_PARSER_GEN4_FORWARD_FEED_INTERVAL_SECONDS: int = Field(default=120, ge=30, le=3600)\n    CANONICAL_PARSER_GEN4_FORWARD_FEED_MAX_REQUESTS_PER_RUN: int = Field(default=4, ge=1, le=20)\n    CANONICAL_PARSER_GEN4_FORWARD_FEED_PAGE_SIZE: int = Field(default=100, ge=10, le=100)\n    CANONICAL_PARSER_GEN4_FORWARD_FEED_OVERLAP_SECONDS: int = Field(default=90, ge=0, le=300)\n    CANONICAL_PARSER_GEN4_FORWARD_FEED_LEASE_SECONDS: int = Field(default=180, ge=60, le=3600)\n    CANONICAL_PARSER_GEN4_FORWARD_FEED_DAILY_REQUEST_CAP: int = Field(default=2000, ge=1, le=1000000)\n    # END M56-M57 GEN4 FORWARD AUTOMATIC FEED\n'''
    path.write_text(replace_once(text, anchor, block, "config"), encoding="utf-8")
    return True


def patch_env(path: Path) -> bool:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if "CANONICAL_PARSER_GEN4_FORWARD_FEED_ENABLED=" in text:
        return False
    suffix = '''\n# M56-M57 Gen4 forward incremental acquisition and embedded scheduler\nCANONICAL_PARSER_GEN4_FORWARD_FEED_ENABLED=false\nCANONICAL_PARSER_GEN4_FORWARD_FEED_AUTOSTART=false\nCANONICAL_PARSER_GEN4_FORWARD_FEED_INTERVAL_SECONDS=120\nCANONICAL_PARSER_GEN4_FORWARD_FEED_MAX_REQUESTS_PER_RUN=4\nCANONICAL_PARSER_GEN4_FORWARD_FEED_PAGE_SIZE=100\nCANONICAL_PARSER_GEN4_FORWARD_FEED_OVERLAP_SECONDS=90\nCANONICAL_PARSER_GEN4_FORWARD_FEED_LEASE_SECONDS=180\nCANONICAL_PARSER_GEN4_FORWARD_FEED_DAILY_REQUEST_CAP=2000\n'''
    path.write_text(text.rstrip() + suffix, encoding="utf-8")
    return True


def patch_schema(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if SCHEMA_MARKER in text:
        return False
    anchor = '''class CanonicalParserGen4ForwardCampaignStopRequest(BaseModel):\n    campaign_id: str = Field(min_length=36, max_length=36)\n    confirmation: str = Field(default="", max_length=320)\n    observed_at: datetime | None = None\n    actor_label: str | None = Field(default=None, max_length=80)\n    note: str | None = Field(default=None, max_length=500)\n\n\n'''
    block = anchor + '''# BEGIN M56-M57 GEN4 FORWARD AUTOMATIC FEED\nclass CanonicalParserGen4ForwardFeedConfigureRequest(BaseModel):\n    campaign_id: str = Field(min_length=36, max_length=36)\n    confirmation: str = Field(default="", max_length=320)\n    enabled: bool = True\n    interval_seconds: int | None = Field(default=None, ge=30, le=3600)\n    max_requests_per_run: int | None = Field(default=None, ge=1, le=20)\n    page_size: int | None = Field(default=None, ge=10, le=100)\n    overlap_seconds: int | None = Field(default=None, ge=0, le=300)\n\n\nclass CanonicalParserGen4ForwardFeedPollRequest(BaseModel):\n    campaign_id: str = Field(min_length=36, max_length=36)\n    confirmation: str = Field(default="", max_length=320)\n    observed_at: datetime | None = None\n\n\n# END M56-M57 GEN4 FORWARD AUTOMATIC FEED\n\n\n'''
    path.write_text(replace_once(text, anchor, block, "schemas"), encoding="utf-8")
    return True


def patch_models(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    changed = False
    if "from backend.app.models.gen4_forward_feed import" not in text:
        anchor = '''from backend.app.models.gen4_forward_shadow import (\n    CanonicalParserGen4ForwardCampaign,\n    CanonicalParserGen4ForwardCycle,\n    CanonicalParserGen4ForwardDecision,\n)\n'''
        block = anchor + '''from backend.app.models.gen4_forward_feed import (\n    CanonicalParserGen4ForwardFeedRun,\n    CanonicalParserGen4ForwardFeedState,\n)\n'''
        text = replace_once(text, anchor, block, "models init")
        changed = True
    if '    "CanonicalParserGen4ForwardFeedState",\n' not in text:
        all_anchor = '    "CanonicalParserGen4ForwardDecision",\n'
        all_block = all_anchor + '    "CanonicalParserGen4ForwardFeedState",\n    "CanonicalParserGen4ForwardFeedRun",\n'
        text = replace_once(text, all_anchor, all_block, "models __all__")
        changed = True
    if changed:
        path.write_text(text, encoding="utf-8")
    return changed


def patch_main(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    changed = False
    if "from backend.app.services.gen4_forward_feed_runtime import" not in text:
        anchor = '''from backend.app.services.live_position_monitor_runtime import (\n    live_position_monitor_runtime,\n)\n'''
        block = anchor + '''from backend.app.services.gen4_forward_feed_runtime import (\n    gen4_forward_feed_runtime,\n)\n'''
        text = replace_once(text, anchor, block, "main runtime import")
        changed = True

    if "CanonicalParserGen4ForwardFeedConfigureRequest" not in text:
        anchor = '''    CanonicalParserGen4ForwardCampaignStopRequest,\n'''
        block = anchor + '''    CanonicalParserGen4ForwardFeedConfigureRequest,\n    CanonicalParserGen4ForwardFeedPollRequest,\n'''
        text = replace_once(text, anchor, block, "main schema imports")
        changed = True

    if "blockchain_parser_gen4_forward_feed_service" not in text:
        anchor = '''from backend.app.services.blockchain_parser_gen4_forward_shadow_service import (\n    CanonicalParserGen4ForwardShadowError,\n    get_gen4_forward_campaign,\n    get_gen4_forward_status,\n    preview_gen4_forward_campaign,\n    run_gen4_forward_cycle,\n    start_gen4_forward_campaign,\n    stop_gen4_forward_campaign,\n)\n'''
        block = anchor + '''from backend.app.services.blockchain_parser_gen4_forward_feed_service import (\n    CanonicalParserGen4ForwardFeedError,\n    configure_gen4_forward_feed,\n    get_gen4_forward_feed_status,\n    run_gen4_forward_feed_poll,\n)\n'''
        text = replace_once(text, anchor, block, "main service import")
        changed = True

    if "await gen4_forward_feed_runtime.start()" not in text:
        text = replace_once(
            text,
            "    await live_position_monitor_runtime.start()\n",
            "    await live_position_monitor_runtime.start()\n    await gen4_forward_feed_runtime.start()\n",
            "lifespan start",
        )
        text = replace_once(
            text,
            "        await live_position_monitor_runtime.stop()\n",
            "        await gen4_forward_feed_runtime.stop()\n        await live_position_monitor_runtime.stop()\n",
            "lifespan stop",
        )
        changed = True

    if MAIN_MARKER not in text:
        anchor = "# END M52-M53 GEN4 STRICT FORWARD SHADOW CAMPAIGN\n"
        endpoints = '''# END M52-M53 GEN4 STRICT FORWARD SHADOW CAMPAIGN\n\n# BEGIN M56-M57 GEN4 FORWARD AUTOMATIC FEED\n@app.get("/integrity/parser-gen4-forward/feed/status", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])\ndef read_gen4_forward_feed_status_endpoint(db: Session = Depends(get_db)):\n    result = get_gen4_forward_feed_status(db)\n    result["worker_running"] = gen4_forward_feed_runtime.running\n    return result\n\n\n@app.post("/integrity/parser-gen4-forward/feed/configure", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])\ndef configure_gen4_forward_feed_endpoint(\n    request: CanonicalParserGen4ForwardFeedConfigureRequest,\n    db: Session = Depends(get_db),\n):\n    try:\n        result = configure_gen4_forward_feed(\n            db,\n            campaign_id=request.campaign_id,\n            confirmation=request.confirmation,\n            enabled=request.enabled,\n            interval_seconds=request.interval_seconds,\n            max_requests_per_run=request.max_requests_per_run,\n            page_size=request.page_size,\n            overlap_seconds=request.overlap_seconds,\n        )\n        db.commit()\n        result["worker_running"] = gen4_forward_feed_runtime.running\n        return result\n    except CanonicalParserGen4ForwardFeedError as exception:\n        db.rollback()\n        raise HTTPException(\n            status_code=exception.status_code,\n            detail={"code": exception.code, "message": str(exception)},\n        ) from exception\n\n\n@app.post("/integrity/parser-gen4-forward/feed/poll", tags=["Blockchain Integrity"], dependencies=[Depends(require_automation_key)])\ndef run_gen4_forward_feed_poll_endpoint(\n    request: CanonicalParserGen4ForwardFeedPollRequest,\n    db: Session = Depends(get_db),\n):\n    try:\n        result = run_gen4_forward_feed_poll(\n            db,\n            campaign_id=request.campaign_id,\n            confirmation=request.confirmation,\n            trigger="MANUAL",\n            observed_at=request.observed_at,\n        )\n        db.commit()\n        return result\n    except CanonicalParserGen4ForwardFeedError as exception:\n        db.rollback()\n        raise HTTPException(\n            status_code=exception.status_code,\n            detail={"code": exception.code, "message": str(exception)},\n        ) from exception\n# END M56-M57 GEN4 FORWARD AUTOMATIC FEED\n'''
        text = replace_once(text, anchor, endpoints, "main endpoints")
        changed = True

    if changed:
        path.write_text(text, encoding="utf-8")
    return changed


def patch_head_test(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    if 'scripts.get_heads() == ["a5e7c1d4b926"]' in text:
        return False
    old = '    assert scripts.get_heads() == ["f4d6a9c2b813"]'
    new = (
        '    assert scripts.get_revision("a5e7c1d4b926").down_revision == "f4d6a9c2b813"\n'
        '    assert scripts.get_heads() == ["a5e7c1d4b926"]'
    )
    if old not in text:
        raise RuntimeError(f"Assertion head f4 mancante: {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    targets = {
        "config": root / "backend/app/core/config.py",
        "env": root / ".env.example",
        "schema": root / "backend/app/schemas/blockchain_integrity.py",
        "models": root / "backend/app/models/__init__.py",
        "main": root / "backend/app/main.py",
        "test_m47": root / "tests/test_parser_gen4_profitability_m47.py",
        "test_m52": root / "tests/test_gen4_forward_shadow_m52_m53.py",
    }
    for name, path in targets.items():
        if not path.exists():
            raise RuntimeError(f"File richiesto mancante ({name}): {path}")
    if args.check_only:
        print("M56_M57_SEMANTIC_PATCH_CHECK=OK")
        return 0
    changes = []
    for name, func in (
        ("config", patch_config),
        ("env", patch_env),
        ("schema", patch_schema),
        ("models", patch_models),
        ("main", patch_main),
        ("test_m47", patch_head_test),
        ("test_m52", patch_head_test),
    ):
        if func(targets[name]):
            changes.append(name)
    print("M56_M57_SEMANTIC_PATCH=OK")
    print("CHANGES=" + (",".join(changes) if changes else "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
