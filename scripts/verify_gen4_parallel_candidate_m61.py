from __future__ import annotations

import argparse
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CURRENT_PROJECT_HEAD = "e4c7a9d1b268"
M61_REVISION = "c8a1f3d6e942"
M61_PARENT_REVISION = "b6f8d2e4c731"


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
    heads = scripts.get_heads()
    if heads != [CURRENT_PROJECT_HEAD]:
        raise AssertionError(f"Alembic head inattesa: {heads}")
    revision = scripts.get_revision(M61_REVISION)
    if revision is None or revision.down_revision != M61_PARENT_REVISION:
        raise AssertionError("Catena Alembic M61 non consecutiva")
    lineage = {
        item.revision
        for item in scripts.iterate_revisions(CURRENT_PROJECT_HEAD, "base")
    }
    if M61_REVISION not in lineage:
        raise AssertionError("La revision M61 non è antenata della head corrente")

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
        "_proof_active_copyability_campaigns",
        "GEN4_COPYABILITY_PROOF_ACTIVE_CAMPAIGN_REQUIRED",
        "record_gen4_copyability_recovery_events",
        "record_gen4_copyability_raw_recovery_events",
        "M63_ACTIVE_CANDIDATE_LINEAGE",
        "GEN4_QUALIFIED_CANDIDATE_LINEAGE_NOT_PROOF_ACTIVE",
        "campaigns_touched",
        "per_campaign",
        "m61_parallel_candidate_support",
        "RIGIDLY_VERIFIED_QUALIFIED_CANDIDATE_SET",
        '"automatic_live_activation": False',
    )
    fastpath_text = require_text(
        PROJECT_ROOT / "backend/app/services/gen4_fastpath_shadow_service.py",
        "_proof_active_fastpath_campaigns",
        "webhook_status == \"ACTIVE\"",
        "webhook_id.is_not(None)",
        "webhook_configured_at.is_not(None)",
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
    rollback_text = require_text(
        PROJECT_ROOT / "scripts/rollback_gen4_parallel_candidate_m61.py",
        "Webhook Gen4 per ID non coincide",
        "current_addresses != PRIMARY_WALLETS",
        "STOP_CANDIDATE_PRESERVE_EVIDENCE",
    )
    if '"transactionTypes": ["ANY"]' in webhook_configurator_text:
        raise AssertionError("Raw webhook configurator usa ancora transactionTypes")
    if 'f"{HELIUS_WEBHOOK_API}/{selected_id}"' not in webhook_configurator_text:
        raise AssertionError("Webhook configurator non verifica il provider per ID")
    if '"transactionTypes": ["ANY"]' in activation_text:
        raise AssertionError("M61 activation raw webhook usa ancora transactionTypes")
    if 'f"{HELIUS_WEBHOOK_API}/{state.webhook_id}"' not in activation_text:
        raise AssertionError("M61 activation non verifica il provider per ID")
    if '"transactionTypes": ["ANY"]' in rollback_text:
        raise AssertionError("M61 rollback raw webhook usa ancora transactionTypes")
    if 'f"{HELIUS_WEBHOOK_API}/{identifier}"' not in rollback_text:
        raise AssertionError("M61 rollback non verifica il provider per ID")
    if service_text.count("_proof_active_copyability_campaigns(db)") < 2:
        raise AssertionError("Proof boundary non copre webhook e queue processing")

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
            fastpath_text,
            worker_text,
            main_text,
            schema_text,
            panel_text,
            api_text,
            migration_text,
            activation_text,
            webhook_configurator_text,
            rollback_text,
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

    webhook_route_marker = (
        '@app.post(\n'
        '    "/integrity/parser-gen4-copyability/webhook/helius",'
    )
    webhook_route_start = main_text.find(webhook_route_marker)
    if webhook_route_start < 0:
        raise AssertionError("Route webhook Gen4 non localizzata nel sorgente")
    next_route_start = main_text.find("\n@app.", webhook_route_start + len(webhook_route_marker))
    public_block = (
        main_text[webhook_route_start:]
        if next_route_start < 0
        else main_text[webhook_route_start:next_route_start]
    )
    if "require_automation_key" in public_block:
        raise AssertionError("Webhook pubblico dipende dalla automation key")
    if "authorization" not in public_block.lower():
        raise AssertionError("Authorization webhook assente")

    print("GEN4_PARALLEL_CANDIDATE_M61_CONTRACT=OK")
    print("STRUCTURE_ONLY=" + ("YES" if args.structure_only else "NO"))
    print(f"ALEMBIC_HEAD={CURRENT_PROJECT_HEAD}")
    print(f"ALEMBIC_M61_REVISION={M61_REVISION}")
    print("ALEMBIC_M61_ANCESTOR_OF_CURRENT_HEAD=YES")
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
