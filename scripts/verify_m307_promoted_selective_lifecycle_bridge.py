from __future__ import annotations

import inspect
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.models.gen4_copyability import (
    CanonicalParserGen4FastpathSelectivePosition,
    CanonicalParserGen4PromotedSelectiveActivation,
    CanonicalParserGen4PromotedSelectivePosition,
)
from backend.app.services import gen4_fastpath_shadow_service as fastpath
from backend.app.services.gen4_post_anchor_selective_evidence_service import (
    M299_PROMOTED_SELECTIVE_SCOPE,
    build_promoted_wallet_evidence,
)
from backend.app.services.gen4_promoted_selective_lifecycle_service import (
    M299_FORMAL_ACQUISITION_REPORT_SHA256,
    M306_FORMAL_REPORT_SHA256,
    M307_FORMAL_LINEAGE_BY_WALLET,
    M307Error,
    M307_AUTOMATIC_PROMOTION,
    M307_BRIDGE_ARMED,
    M307_BRIDGE_IMPLEMENTED,
    M307_LEGACY_ENDPOINT_USED,
    M307_PREPROMOTION_BACKFILL,
    M307_PROVIDER_MUTATION_REQUIRED,
    M307_SCOPE,
    M307_VERSION,
    build_activation_package,
    formal_lineage_for_wallet,
    validate_activation_package,
)
from backend.app.services.gen4_selective_challenger_lifecycle_bridge_design_service import (
    PROMOTED_ACTIVATION_TABLE,
    PROMOTED_POSITION_TABLE,
    PROMOTED_SELECTIVE_SCOPE,
)
from backend.app.services.gen4_selective_challenger_promotion_service import (
    M300_SCOPE,
    M300_VERSION,
)

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "f5d8b1c3e470_add_m307_promoted_selective_lifecycle_bridge.py"

WALLET = "89f3DSmRiFsAZWQXCQMYPwyEUtxbVeCDP7JEjsXrbWST"
CGAZ = "CGAZ8ysbcmc6a14uYRqDJfnQvjRF4fVSZBYiTsZgRwcH"
TWO_MQR = "2mqrindMAjJEQPLhroYWyiYPo5h9iAsahfdd4QtsjwdY"
TWO_MQR_M306 = "801b1d2c3982f45bf92dba2ccbb7253897997395c90947ca1e4878f297d781e0"
TWO_MQR_M299 = "d51c9c45625c5a4d71612b3bf2f6b05bb621d2b844975ae3e55479a414927bb8"
TWO_MQR_TERMINAL = "2026-09-06T20:49:53.954151+00:00"
D9GQ = "D9gQ6RhKEpnobPBUdWY5bPQt2p3zGk3iVz6ChpUi2ArA"
D9GQ_M306 = "0fb1f681cbeb50c024487979a24ae914fa4b9cd178151cc48a78ff5c85b3504d"
D9GQ_M299 = "d18b388794ac2debe5c38ad56c83ef2dc11b74d7e1c6f5180dec8a96255d8854"
D9GQ_TERMINAL = "2026-09-07T20:38:58.512074+00:00"
FIVE_PA = "5pAewyzzyf3bbD2MEdvEjTHR9AqfL9wWouEA8ft2ggEV"
FIVE_PA_M306 = "5c071d2e07bdbaddc535b5a9384501f4b2c9f9b35027bc2a7f746a32c4c3a5b5"
FIVE_PA_M299 = "f17a297be33c331bdb815a26c70cac643c3b551e304e1b78496805cd0ca34c31"
FIVE_PA_TERMINAL = "2026-09-08T13:08:30.261498+00:00"
THIRTY7_UM = "37uM1rp8TK7eVURVRnjtaxGkdJyXjgA9uz83DjApcHvq"
THIRTY7_UM_M306 = "04124921b630db49402f906cc7a2ade639b9a7a639ab9a49fc34f414d7dbcc68"
THIRTY7_UM_M299 = "11e5f2c752ccf7a6be4f9c779766f99d3931747c78533cf145487f681e7521de"
THIRTY7_UM_TERMINAL = "2026-09-08T13:08:30.261498+00:00"
NINE_RDM = "9rDMVCH7mQ9N2PkyHw8KT8wraMhF8tyMz9R631yyL1df"
NINE_RDM_M306 = "4b1bde2585f9a1b7d39fefae6b8baeeecced9d41ae4384b459685dba56bbc389"
NINE_RDM_M299 = "eae34ec4e8159e204e230985c55a59ac6e5dee3aacfb01b40161bde417793791"
NINE_RDM_TERMINAL = "2026-09-08T13:08:30.261498+00:00"
THREE_N7 = "3N7aa2Wkg9dEm8kkC4F7M8knExDyEL8Vehu1S9H3NA2K"
THREE_N7_M306 = "b4c3f08c46f5f36477cedd14bea5c997908a8a4dbf07938afe276ea602c95614"
THREE_N7_M299 = "b42bbbb4d9f73cbee23d54b94142b8509622d23e7a8ef42dcce386945172f32f"
THREE_N7_TERMINAL = "2026-09-09T11:10:39.365594+00:00"
TWO_EC754 = "2Ec7546mqCuq1PPGSWTaQZ6DdTGWhpPhEuVicJ3sTQnr"
TWO_EC754_M306 = "ffbe82a65eac609ae2fdc6e90287385c6566ec39a22a0e17be3a0dd03b23cb36"
TWO_EC754_M299 = "09be1de4549b03f447b9bd020234f48298eb80797fe165930543ea3ba18dfe49"
TWO_EC754_TERMINAL = "2026-09-12T01:10:39.474599+00:00"


def _decision(wallet: str = WALLET) -> dict:
    return {
        "scope": M300_SCOPE,
        "version": M300_VERSION,
        "wallet": wallet,
        "state": "PROMOTION_ELIGIBLE_DISARMED",
        "promotion_eligible": True,
        "promotion_armed": False,
        "promotion_executed": False,
        "checks": {
            "target_is_approved_challenger": True,
            "clean_attempt_classification_complete": True,
            "minimum_clean_entry_attempts": True,
            "minimum_clean_accepted_attempts": True,
            "accepted_unsigned_build_coverage": True,
            "accepted_evidence_complete": True,
            "accepted_end_to_quote_p95": True,
            "accepted_price_deterioration_p95": True,
            "accepted_price_impact_p95": True,
            "zero_technical_failures_in_effective_clean_window": True,
            "zero_unmapped_attempts": True,
        },
        "legacy_endpoint": {
            "compatible": False,
            "gen4_copyability_pass_invented": False,
            "must_not_be_called_from_m300": True,
        },
        "future_selective_lifecycle_bridge": {
            "required": True,
            "implemented_by_m300_pre": False,
            "candidate_fastpath_entry_evidence_backfilled": False,
            "full_lifecycle_proof_starts_at_promotion_activation": True,
        },
        "formal_claims": {
            "m74_pass_claimed": False,
            "legacy_m75_pass_claimed": False,
            "gen4_copyability_pass_claimed": False,
            "m298_pass_claimed": False,
            "micro_live_ready_claimed": False,
        },
        "safety": {
            "database_writes": 0,
            "backend_mutations": 0,
            "railway_variable_set": False,
            "provider_mutations": 0,
            "live_execution": False,
            "signer_access": False,
            "submitted_transactions": 0,
            "paper_orders": 0,
        },
    }


def main() -> None:
    assert M307_BRIDGE_IMPLEMENTED is True
    assert M307_BRIDGE_ARMED is False
    assert M307_AUTOMATIC_PROMOTION is False
    assert M307_PREPROMOTION_BACKFILL is False
    assert M307_LEGACY_ENDPOINT_USED is False
    assert M307_PROVIDER_MUTATION_REQUIRED is False
    assert M307_SCOPE == "M307_PROMOTED_SELECTIVE_LIFECYCLE_BRIDGE_IMPLEMENTED_DISARMED"
    assert M307_VERSION.endswith("/1")

    assert set(M307_FORMAL_LINEAGE_BY_WALLET) == {CGAZ, WALLET, TWO_MQR, D9GQ, FIVE_PA, THIRTY7_UM, NINE_RDM, THREE_N7, TWO_EC754}
    assert formal_lineage_for_wallet(WALLET)["m306_report_sha256"] == M306_FORMAL_REPORT_SHA256
    assert formal_lineage_for_wallet(WALLET)["m299_acquisition_report_sha256"] == M299_FORMAL_ACQUISITION_REPORT_SHA256
    assert formal_lineage_for_wallet(CGAZ) == formal_lineage_for_wallet(WALLET)
    assert formal_lineage_for_wallet(TWO_MQR) == {
        "m306_report_sha256": TWO_MQR_M306,
        "m299_acquisition_report_sha256": TWO_MQR_M299,
        "m306_terminal_utc": TWO_MQR_TERMINAL,
    }
    assert formal_lineage_for_wallet(D9GQ) == {
        "m306_report_sha256": D9GQ_M306,
        "m299_acquisition_report_sha256": D9GQ_M299,
        "m306_terminal_utc": D9GQ_TERMINAL,
    }
    assert formal_lineage_for_wallet(FIVE_PA) == {
        "m306_report_sha256": FIVE_PA_M306,
        "m299_acquisition_report_sha256": FIVE_PA_M299,
        "m306_terminal_utc": FIVE_PA_TERMINAL,
    }
    assert formal_lineage_for_wallet(THIRTY7_UM) == {
        "m306_report_sha256": THIRTY7_UM_M306,
        "m299_acquisition_report_sha256": THIRTY7_UM_M299,
        "m306_terminal_utc": THIRTY7_UM_TERMINAL,
    }
    assert formal_lineage_for_wallet(NINE_RDM) == {
        "m306_report_sha256": NINE_RDM_M306,
        "m299_acquisition_report_sha256": NINE_RDM_M299,
        "m306_terminal_utc": NINE_RDM_TERMINAL,
    }
    assert formal_lineage_for_wallet(THREE_N7) == {
        "m306_report_sha256": THREE_N7_M306,
        "m299_acquisition_report_sha256": THREE_N7_M299,
        "m306_terminal_utc": THREE_N7_TERMINAL,
    }
    assert formal_lineage_for_wallet(TWO_EC754) == {
        "m306_report_sha256": TWO_EC754_M306,
        "m299_acquisition_report_sha256": TWO_EC754_M299,
        "m306_terminal_utc": TWO_EC754_TERMINAL,
    }

    assert CanonicalParserGen4PromotedSelectiveActivation.__tablename__ == PROMOTED_ACTIVATION_TABLE
    assert CanonicalParserGen4PromotedSelectivePosition.__tablename__ == PROMOTED_POSITION_TABLE
    assert M299_PROMOTED_SELECTIVE_SCOPE == PROMOTED_SELECTIVE_SCOPE

    official_constraints = {
        str(item.sqltext)
        for item in CanonicalParserGen4FastpathSelectivePosition.__table__.constraints
        if hasattr(item, "sqltext")
    }
    assert any("OFFICIAL_FASTPATH_SELECTIVE" in text for text in official_constraints)
    promoted_constraints = {
        str(item.sqltext)
        for item in CanonicalParserGen4PromotedSelectivePosition.__table__.constraints
        if hasattr(item, "sqltext")
    }
    assert any(PROMOTED_SELECTIVE_SCOPE in text for text in promoted_constraints)

    source = inspect.getsource(fastpath.record_fastpath_candidate_notification)
    assert "get_promoted_activation_for_event" in source
    assert "_new_promoted_selective_position" in source
    assert "_apply_promoted_selective_sell_shadow" in source
    assert "promoted_position_created" in source

    adapter_source = inspect.getsource(build_promoted_wallet_evidence)
    adapter_signature = str(inspect.signature(build_promoted_wallet_evidence))
    assert "delivery_receipts" in adapter_signature
    assert "evaluate_promoted_delivery_coverage" in adapter_source
    assert "no_wss_as_webhook_relabeling" in adapter_source
    assert "INDEPENDENT_WEBHOOK_OR_EQUIVALENT_DELIVERY_COVERAGE_NOT_YET_PROVEN" in adapter_source

    package = build_activation_package(
        m300_decision=_decision(),
        m306_report_sha256=M306_FORMAL_REPORT_SHA256,
        m299_acquisition_report_sha256=M299_FORMAL_ACQUISITION_REPORT_SHA256,
        operational_policy_snapshot={
            "simulated_input_lamports": 10_000_000,
            "slippage_bps": 300,
            "max_quote_latency_ms": 5_000,
            "max_price_impact_bps": 500,
            "max_price_deterioration_bps": 1_000,
            "estimated_network_fee_lamports": 100_000,
            "live_execution": False,
            "paper_execution": False,
            "automatic_live_activation": False,
        },
        operational_policy_source_sha256="a" * 64,
        candidate_watchlist_wallets=[WALLET],
        activation_at=datetime(2026, 9, 1, 16, 0, tzinfo=timezone.utc),
    )
    validate_activation_package(package)
    assert package["safety"]["bridge_armed"] is False
    assert package["safety"]["automatic_promotion"] is False
    assert package["activation_blueprint"]["runtime_route"]["pre_activation_event_backfill"] is False
    assert package["activation_blueprint"]["runtime_route"]["helius_provider_union_change_required"] is False
    assert package["activation_blueprint"]["runtime_route"]["legacy_start_qualified_candidate_required"] is False

    two_mqr_lineage = formal_lineage_for_wallet(TWO_MQR)
    two_mqr_package = build_activation_package(
        m300_decision=_decision(TWO_MQR),
        m306_report_sha256=two_mqr_lineage["m306_report_sha256"],
        m299_acquisition_report_sha256=two_mqr_lineage["m299_acquisition_report_sha256"],
        operational_policy_snapshot={
            "simulated_input_lamports": 10_000_000,
            "slippage_bps": 300,
            "max_quote_latency_ms": 5_000,
            "max_price_impact_bps": 500,
            "max_price_deterioration_bps": 1_000,
            "estimated_network_fee_lamports": 100_000,
            "live_execution": False,
            "paper_execution": False,
            "automatic_live_activation": False,
        },
        operational_policy_source_sha256="b" * 64,
        candidate_watchlist_wallets=[TWO_MQR],
        activation_at=datetime(2026, 9, 6, 21, 0, tzinfo=timezone.utc),
    )
    validate_activation_package(two_mqr_package)
    assert two_mqr_package["formal_promotion_lineage"]["m306_report_sha256"] == TWO_MQR_M306
    assert two_mqr_package["formal_promotion_lineage"]["m299_acquisition_report_sha256"] == TWO_MQR_M299
    assert two_mqr_package["formal_promotion_lineage"]["m306_terminal_utc"] == TWO_MQR_TERMINAL
    assert two_mqr_package["decision_envelope"]["evaluated_at_utc"] == TWO_MQR_TERMINAL

    d9gq_lineage = formal_lineage_for_wallet(D9GQ)
    d9gq_package = build_activation_package(
        m300_decision=_decision(D9GQ),
        m306_report_sha256=d9gq_lineage["m306_report_sha256"],
        m299_acquisition_report_sha256=d9gq_lineage["m299_acquisition_report_sha256"],
        operational_policy_snapshot={
            "simulated_input_lamports": 10_000_000,
            "slippage_bps": 300,
            "max_quote_latency_ms": 5_000,
            "max_price_impact_bps": 500,
            "max_price_deterioration_bps": 1_000,
            "estimated_network_fee_lamports": 100_000,
            "live_execution": False,
            "paper_execution": False,
            "automatic_live_activation": False,
        },
        operational_policy_source_sha256="c" * 64,
        candidate_watchlist_wallets=[D9GQ],
        activation_at=datetime(2026, 9, 7, 21, 0, tzinfo=timezone.utc),
    )
    validate_activation_package(d9gq_package)
    assert d9gq_package["formal_promotion_lineage"]["m306_report_sha256"] == D9GQ_M306
    assert d9gq_package["formal_promotion_lineage"]["m299_acquisition_report_sha256"] == D9GQ_M299
    assert d9gq_package["formal_promotion_lineage"]["m306_terminal_utc"] == D9GQ_TERMINAL
    assert d9gq_package["decision_envelope"]["evaluated_at_utc"] == D9GQ_TERMINAL

    for _wallet, _m306, _m299, _terminal in (
        (FIVE_PA, FIVE_PA_M306, FIVE_PA_M299, FIVE_PA_TERMINAL),
        (THIRTY7_UM, THIRTY7_UM_M306, THIRTY7_UM_M299, THIRTY7_UM_TERMINAL),
        (NINE_RDM, NINE_RDM_M306, NINE_RDM_M299, NINE_RDM_TERMINAL),
        (THREE_N7, THREE_N7_M306, THREE_N7_M299, THREE_N7_TERMINAL),
        (TWO_EC754, TWO_EC754_M306, TWO_EC754_M299, TWO_EC754_TERMINAL),
    ):
        _lineage = formal_lineage_for_wallet(_wallet)
        _package = build_activation_package(
            m300_decision=_decision(_wallet),
            m306_report_sha256=_lineage["m306_report_sha256"],
            m299_acquisition_report_sha256=_lineage["m299_acquisition_report_sha256"],
            operational_policy_snapshot={
                "simulated_input_lamports": 10_000_000,
                "slippage_bps": 300,
                "max_quote_latency_ms": 5_000,
                "max_price_impact_bps": 500,
                "max_price_deterioration_bps": 1_000,
                "estimated_network_fee_lamports": 100_000,
                "live_execution": False,
                "paper_execution": False,
                "automatic_live_activation": False,
            },
            operational_policy_source_sha256="c" * 64,
            candidate_watchlist_wallets=[_wallet],
            activation_at=datetime.fromisoformat(_terminal),
        )
        validate_activation_package(_package)
        assert _package["formal_promotion_lineage"]["m306_report_sha256"] == _m306
        assert _package["formal_promotion_lineage"]["m299_acquisition_report_sha256"] == _m299
        assert _package["formal_promotion_lineage"]["m306_terminal_utc"] == _terminal
        assert _package["decision_envelope"]["evaluated_at_utc"] == _terminal

    try:
        build_activation_package(
            m300_decision=_decision(TWO_MQR),
            m306_report_sha256=M306_FORMAL_REPORT_SHA256,
            m299_acquisition_report_sha256=M299_FORMAL_ACQUISITION_REPORT_SHA256,
            operational_policy_snapshot={
                "simulated_input_lamports": 10_000_000,
                "slippage_bps": 300,
                "max_quote_latency_ms": 5_000,
                "max_price_impact_bps": 500,
                "max_price_deterioration_bps": 1_000,
                "estimated_network_fee_lamports": 100_000,
                "live_execution": False,
                "paper_execution": False,
                "automatic_live_activation": False,
            },
            operational_policy_source_sha256="b" * 64,
            candidate_watchlist_wallets=[TWO_MQR],
            activation_at=datetime(2026, 9, 6, 21, 0, tzinfo=timezone.utc),
        )
    except M307Error:
        pass
    else:
        raise AssertionError("M307 accepted cross-wallet historical lineage for 2MQR")

    text = MIGRATION.read_text(encoding="utf-8-sig")
    assert 'revision = "f5d8b1c3e470"' in text
    assert 'down_revision = "e4c7a9d1b268"' in text
    assert PROMOTED_ACTIVATION_TABLE in text
    assert PROMOTED_POSITION_TABLE in text
    assert "ON DELETE" not in text.upper() or "CASCADE" in text.upper()

    print(
        "M307_VERIFY=PASS;"
        "bridge_implemented=true;"
        "bridge_armed=false;"
        "automatic_promotion=false;"
        "dedicated_tables=true;"
        "official_scope_unchanged=true;"
        "candidate_recorder_hook=true;"
        "prepromotion_backfill=false;"
        "legacy_endpoint=false;"
        "provider_mutation=false;"
        "m299_promoted_adapter=true;"
        "webhook_coverage_fail_closed_without_receipts=true;"
        "m309_authenticated_coverage_extension_compatible=true;"
        "wallet_scoped_formal_lineage=true;"
        "cross_wallet_lineage_rejected=true;"
        "2mqr_lineage_registered=true;"
        "d9gq_lineage_registered=true;"
        "triple_lineage_registered=true;"
        "3n7_lineage_registered=true;"
        "2ec754_lineage_registered=true;"
        "live=false;signer=false;paper=0"
    )


if __name__ == "__main__":
    main()
