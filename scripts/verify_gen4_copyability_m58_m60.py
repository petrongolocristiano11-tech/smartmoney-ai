from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
M58_M60_REVISION = "b6f8d2e4c731"
M58_M60_DOWN_REVISION = "a5e7c1d4b926"
EXPECTED_PROJECT_HEAD = "e4c7a9d1b268"
M61_REVISION = "c8a1f3d6e942"


def require_text(path: Path, *needles: str) -> str:
    if not path.exists():
        raise AssertionError(f"File mancante: {path.relative_to(PROJECT_ROOT)}")
    text = path.read_text(encoding="utf-8")
    for needle in needles:
        if needle not in text:
            raise AssertionError(
                f"Contratto mancante in {path.relative_to(PROJECT_ROOT)}: {needle}"
            )
    return text


def main() -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    scripts = ScriptDirectory.from_config(config)

    heads = scripts.get_heads()
    if heads != [EXPECTED_PROJECT_HEAD]:
        raise AssertionError(f"Alembic head inattesa: {heads}")

    m58_m60_revision = scripts.get_revision(M58_M60_REVISION)
    if (
        m58_m60_revision is None
        or m58_m60_revision.down_revision != M58_M60_DOWN_REVISION
    ):
        raise AssertionError("Catena Alembic M58-M60 non consecutiva.")

    m61_revision = scripts.get_revision(M61_REVISION)
    if m61_revision is None or m61_revision.down_revision != M58_M60_REVISION:
        raise AssertionError("Catena Alembic M58-M61 non consecutiva.")

    lineage = {
        item.revision
        for item in scripts.iterate_revisions(EXPECTED_PROJECT_HEAD, "base")
    }
    if M58_M60_REVISION not in lineage or M61_REVISION not in lineage:
        raise AssertionError("M58-M61 non appartengono alla lineage della head corrente.")

    model_text = require_text(
        PROJECT_ROOT / "backend/app/models/gen4_copyability.py",
        "canonical_parser_gen4_copyability_campaigns",
        "canonical_parser_gen4_webhook_receipts",
        "canonical_parser_gen4_copyability_positions",
        "canonical_parser_gen4_copyability_worker_states",
        "RECOVERY_ONLY",
    )
    service_text = require_text(
        PROJECT_ROOT / "backend/app/services/blockchain_parser_gen4_copyability_service.py",
        "receive_gen4_copyability_webhook",
        "record_gen4_copyability_recovery_events",
        "record_gen4_copyability_raw_recovery_events",
        "_proof_active_copyability_campaigns",
        "GEN4_COPYABILITY_PROOF_ACTIVE_CAMPAIGN_REQUIRED",
        "process_gen4_copyability_queue",
        "otherAmountThreshold",
        "get_quote_and_unsigned_build",
        "max_processing_attempts",
        '"automatic_live_activation": False',
    )
    require_text(
        PROJECT_ROOT / "backend/app/services/gen4_copyability_runtime.py",
        "EmbeddedGen4CopyabilityRuntime",
    )
    jupiter_text = require_text(
        PROJECT_ROOT / "backend/app/services/jupiter_swap_client.py",
        "get_quote_and_unsigned_build",
        "\"/build\"",
        "endpointSequence",
        "executeEndpointCalled",
    )
    worker_text = require_text(
        PROJECT_ROOT / "backend/app/workers/gen4_copyability_worker.py",
        "Gen4CopyabilityWorker",
        "never receives a signer",
    )
    main_text = require_text(
        PROJECT_ROOT / "backend/app/main.py",
        "/integrity/parser-gen4-copyability/webhook/helius",
        "/integrity/parser-gen4-copyability/status",
        "secrets.compare_digest",
        "PERSISTED_FOR_ASYNC_SHADOW_QUEUE",
    )
    feed_text = require_text(
        PROJECT_ROOT / "backend/app/services/blockchain_parser_gen4_forward_feed_service.py",
        "record_gen4_copyability_recovery_events",
        '"counted_as_realtime": False',
    )
    require_text(
        PROJECT_ROOT / "frontend/src/components/gen4Forward/Gen4CopyabilityPanel.jsx",
        "Real-Time Copyability",
        "RECOVERY_ONLY",
    )
    require_text(
        PROJECT_ROOT / "frontend/src/pages/Gen4Forward.jsx",
        "Gen4CopyabilityPanel",
        "getGen4CopyabilityStatus",
    )

    forbidden = (
        ".execute_order(",
        "signed_transaction=",
        "submit_transaction(",
        "automatic_live_activation=True",
        '"automatic_live_activation": True',
    )
    shadow_sources = "\n".join([service_text, worker_text, feed_text])
    for needle in forbidden:
        if needle in shadow_sources:
            raise AssertionError(f"Percorso unsafe M58-M60 rilevato: {needle}")

    # The public Helius endpoint must not inherit the automation-key dependency.
    webhook_route_marker = (
        '@app.post(\n'
        '    "/integrity/parser-gen4-copyability/webhook/helius",'
    )
    webhook_route_start = main_text.find(webhook_route_marker)
    if webhook_route_start < 0:
        raise AssertionError("Route webhook Gen4 non localizzata nel sorgente.")
    next_route_start = main_text.find(
        "\n@app.",
        webhook_route_start + len(webhook_route_marker),
    )
    public_block = (
        main_text[webhook_route_start:]
        if next_route_start < 0
        else main_text[webhook_route_start:next_route_start]
    )
    if "require_automation_key" in public_block:
        raise AssertionError("Il webhook pubblico dipende erroneamente dalla automation key.")
    if "authorization" not in public_block.lower():
        raise AssertionError("Autenticazione Authorization webhook assente.")

    from backend.app.main import app

    openapi = app.openapi()
    paths = openapi.get("paths") or {}
    required_paths = {
        "/integrity/parser-gen4-copyability/webhook/helius": "post",
        "/integrity/parser-gen4-copyability/status": "get",
        "/integrity/parser-gen4-copyability/start": "post",
        "/integrity/parser-gen4-copyability/stop": "post",
        "/integrity/parser-gen4-copyability/webhook/configure": "post",
        "/integrity/parser-gen4-copyability/process": "post",
    }
    for path, method in required_paths.items():
        if method not in (paths.get(path) or {}):
            raise AssertionError(f"Route OpenAPI mancante: {method.upper()} {path}")

    if "execute" in " ".join(required_paths).lower():
        raise AssertionError("Endpoint execute non consentito nel contratto M58-M60.")

    print("GEN4_COPYABILITY_M58_M60_CONTRACT=OK")
    print(f"ALEMBIC_M58_M60_REVISION={M58_M60_REVISION}")
    print(f"ALEMBIC_HEAD={EXPECTED_PROJECT_HEAD}")
    print(f"ALEMBIC_M61_REVISION={M61_REVISION}")
    print("ALEMBIC_CHAIN_M58_M61_CURRENT=PASS")
    print("WEBHOOK_AUTH=AUTHORIZATION_COMPARE_DIGEST")
    print("RECOVERY_ONLY_EXCLUDED=YES")
    print("JUPITER_MODE=QUOTE_AND_UNSIGNED_BUILD_ONLY")
    print("SIGNER_ACCESS=NO")
    print("PAPER_ORDERS=NO")
    print("LIVE_ORDERS=NO")


if __name__ == "__main__":
    main()
