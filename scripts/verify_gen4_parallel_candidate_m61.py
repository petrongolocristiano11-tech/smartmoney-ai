from __future__ import annotations

import argparse
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_HEAD = "c8a1f3d6e942"
PARENT_HEAD = "b6f8d2e4c731"


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
    parser = argparse.ArgumentParser()
    parser.add_argument("--structure-only", action="store_true")
    args = parser.parse_args()

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    if scripts.get_heads() != [EXPECTED_HEAD]:
        raise AssertionError(f"Alembic head inattesa: {scripts.get_heads()}")
    revision = scripts.get_revision(EXPECTED_HEAD)
    if revision is None or revision.down_revision != PARENT_HEAD:
        raise AssertionError("Catena Alembic M61 non consecutiva")

    model_text = require_text(
        PROJECT_ROOT / "backend/app/models/gen4_copyability.py",
        "campaign_role IN ('PRIMARY_FORWARD','QUALIFIED_CANDIDATE')",
        "candidate_key",
        "selection_snapshot",
        "uq_gen4_copy_campaign_candidate_key",
        "uq_gen4_copy_primary_forward",
        "ix_gen4_copy_campaign_role_status",
    )
    service_text = require_text(
        PROJECT_ROOT / "backend/app/services/blockchain_parser_gen4_copyability_service.py",
        "start_gen4_qualified_candidate_campaign",
        "GEN4_QUALIFIED_CANDIDATE_START_CONFIRMATION",
        "_active_copyability_campaigns",
        "campaigns_touched",
        "per_campaign",
        "m61_parallel_candidate_support",
        "RIGIDLY_VERIFIED_QUALIFIED_CANDIDATE_SET",
        '"automatic_live_activation": False',
    )
    worker_text = require_text(
        PROJECT_ROOT / "backend/app/workers/gen4_copyability_worker.py",
        "active_campaigns",
        "PRIMARY_FORWARD",
        "never receives a signer",
    )
    main_text = require_text(
        PROJECT_ROOT / "backend/app/main.py",
        "/integrity/parser-gen4-copyability/start-qualified-candidate",
        "CanonicalParserGen4QualifiedCandidateStartRequest",
        "campaign_id: str | None",
        "PERSISTED_FOR_ASYNC_SHADOW_QUEUE",
    )
    schema_text = require_text(
        PROJECT_ROOT / "backend/app/schemas/blockchain_integrity.py",
        "CanonicalParserGen4QualifiedCandidateStartRequest",
        "candidate_wallets: list[str]",
        "selection_snapshot: dict",
    )
    panel_text = require_text(
        PROJECT_ROOT / "frontend/src/components/gen4Forward/Gen4CopyabilityPanel.jsx",
        "active_campaigns",
        "PRIMARY_FORWARD",
        "Real-Time Copyability Multi-Campaign",
        "una campagna contamini l’altra",
    )
    api_text = require_text(
        PROJECT_ROOT / "frontend/src/services/gen4ForwardApi.js",
        "startGen4QualifiedCandidate",
        "start-qualified-candidate",
        "START_GEN4_QUALIFIED_CANDIDATE_COPYABILITY",
    )
    migration_text = require_text(
        PROJECT_ROOT / "alembic/versions/c8a1f3d6e942_add_gen4_parallel_candidate_copyability.py",
        "uq_gen4_copy_campaign_forward",
        "uq_gen4_copy_campaign_candidate_key",
        "uq_gen4_copy_primary_forward",
        "Downgrade M61 rifiutato",
    )
    activation_text = require_text(
        PROJECT_ROOT / "scripts/activate_gen4_parallel_candidate_m61.py",
        "EXPECTED_PRIMARY_CAMPAIGN_ID",
        "PRIMARY_EVIDENCE_PRESERVED=YES",
        "M61_FAILSAFE_WEBHOOK_RESTORED",
        "M61_FAILSAFE_CANDIDATE_STOPPED",
        "WEBHOOK_WALLET_COUNT=3",
    )
    webhook_configurator_text = require_text(
        PROJECT_ROOT / "scripts/configure_gen4_copyability_helius_webhook.py",
        "active_campaigns",
        "wallet_owners",
        "registered_campaigns",
        "M61_SINGLE_WEBHOOK_UNION_ROUTING=ENABLED",
    )

    forbidden = (
        ".execute_order(",
        "signed_transaction=",
        "submit_transaction(",
        "automatic_live_activation=True",
        '"automatic_live_activation": True',
        "private_key=",
    )
    guarded_sources = "\n".join(
        [
            model_text,
            service_text,
            worker_text,
            main_text,
            schema_text,
            panel_text,
            api_text,
            migration_text,
            activation_text,
            webhook_configurator_text,
        ]
    )
    for needle in forbidden:
        if needle in guarded_sources:
            raise AssertionError(f"Percorso unsafe M61 rilevato: {needle}")

    if "UniqueConstraint(\n            \"forward_campaign_db_id\"" in model_text:
        raise AssertionError("Vecchia unique forward ancora presente nel modello M61")
    if "campaign_role == CAMPAIGN_ROLE_PRIMARY" not in service_text:
        raise AssertionError("Selezione esplicita campagna primaria assente")
    if "campaign_db_id.in_(" not in service_text:
        raise AssertionError("Worker multi-campaign non usa una coda globale isolata")
    if "set(primary_after.get(\"frozen_wallets\")" not in activation_text:
        raise AssertionError("Verifica post-attivazione dei wallet primari assente")

    if not args.structure_only:
        from backend.app.main import app

        openapi = app.openapi()
        paths = openapi.get("paths") or {}
        required_paths = {
            "/integrity/parser-gen4-copyability/webhook/helius": "post",
            "/integrity/parser-gen4-copyability/status": "get",
            "/integrity/parser-gen4-copyability/start": "post",
            "/integrity/parser-gen4-copyability/start-qualified-candidate": "post",
            "/integrity/parser-gen4-copyability/stop": "post",
            "/integrity/parser-gen4-copyability/webhook/configure": "post",
            "/integrity/parser-gen4-copyability/process": "post",
        }
        for path, method in required_paths.items():
            if method not in (paths.get(path) or {}):
                raise AssertionError(f"Route OpenAPI mancante: {method.upper()} {path}")

    public_block = main_text.split(
        '"/integrity/parser-gen4-copyability/webhook/helius"', 1
    )[1].split('"/integrity/parser-gen4-copyability/status"', 1)[0]
    if "require_automation_key" in public_block:
        raise AssertionError("Webhook pubblico dipende dalla automation key")
    if "authorization" not in public_block.lower():
        raise AssertionError("Authorization webhook assente")

    print("GEN4_PARALLEL_CANDIDATE_M61_CONTRACT=OK")
    print("STRUCTURE_ONLY=" + ("YES" if args.structure_only else "NO"))
    print(f"ALEMBIC_HEAD={EXPECTED_HEAD}")
    print("PRIMARY_CAMPAIGN_BACKWARD_COMPATIBILITY=YES")
    print("MULTI_CAMPAIGN_ROUTING=ISOLATED")
    print("SINGLE_HELIUS_WEBHOOK_UNION=YES")
    print("RECOVERY_ONLY_EXCLUDED=YES")
    print("JUPITER_MODE=QUOTE_AND_UNSIGNED_BUILD_ONLY")
    print("SIGNER_ACCESS=NO")
    print("PAPER_ORDERS=NO")
    print("LIVE_ORDERS=NO")


if __name__ == "__main__":
    main()
