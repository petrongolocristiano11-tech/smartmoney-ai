from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FAST = ROOT / "backend/app/services/gen4_fastpath_shadow_service.py"
BRIDGE = ROOT / "backend/app/services/gen4_fastpath_native_m75_evidence_service.py"
M75 = ROOT / "backend/app/services/gen4_zero_helius_final_pre_micro_live_service.py"


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"M282_VERIFY_FAIL:{msg}")


fast = FAST.read_text(encoding="utf-8")
bridge = BRIDGE.read_text(encoding="utf-8")
m75 = M75.read_text(encoding="utf-8")

require('load_fastpath_native_m75_bridge' in fast, 'bridge_not_integrated')
require('result["m75_native_bridge"]' in fast, 'status_missing_bridge')
require('FASTPATH_NATIVE_M75_FORMAL_ARMED = False' in bridge, 'bridge_not_disarmed')
require('"formal_m75_claimed": False' in bridge, 'formal_claim_not_false')
require('"micro_live_execution_authorized": False' in bridge, 'micro_live_not_false')
require('selection.get("formal_m74_pass") is True' in bridge, 'formal_m74_exact_gate_missing')
require('POSTHOC_RECONCILIATION_ONLY' in bridge, 'webhook_role_missing')
require('sign_canary_evidence' in bridge and 'evaluate_m75_canary' in bridge, 'canonical_m75_contract_not_reused')
require('canary_minimum_observation_hours": 24.0' in m75, 'm75_24h_changed')
require('canary_minimum_entry_attempts": 20' in m75, 'm75_attempts_changed')
require('canary_minimum_closed_trades": 10' in m75, 'm75_closed_changed')
require('canary_minimum_webhook_coverage_percent": 95.0' in m75, 'm75_webhook_changed')
require('canary_minimum_unsigned_build_coverage_percent": 100.0' in m75, 'm75_unsigned_changed')
require('canary_maximum_entry_reject_rate_percent": 20.0' in m75, 'm75_reject_changed')
require('canary_maximum_p95_end_to_quote_ms": 5000.0' in m75, 'm75_latency_changed')
require('canary_maximum_p95_price_impact_bps": 500.0' in m75, 'm75_impact_changed')
require('canary_maximum_p95_price_deterioration_bps": 1000.0' in m75, 'm75_deterioration_changed')
require('PERSISTENT_FORWARD_ENTRY_ONLY_NO_24H_CLOSED_WEBHOOK_PROOF' in fast, 'legacy_status_contract_removed')
require('live_execution": False' in bridge and 'signer_access": False' in bridge, 'safety_missing')
print('M282_VERIFY=PASS;bridge_disarmed=true;formal_m74_bypass=false;m75_thresholds_unchanged=true;legacy_status_preserved=true;posthoc_webhook=true')
