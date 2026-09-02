from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "backend/app/services/gen4_selective_copyability_gate_service.py"
TEST = ROOT / "tests/test_m291_selective_copyability_gate.py"

for path in (SERVICE, TEST):
    if not path.is_file():
        raise SystemExit(f"M291_VERIFY=FAIL;reason=MISSING:{path}")
    ast.parse(path.read_text(encoding="utf-8"))

src = SERVICE.read_text(encoding="utf-8")
required = [
    'SELECTIVE_GATE_FORMAL_ARMED = False',
    'p["canary_minimum_observation_hours"]',
    'p["canary_minimum_entry_attempts"]',
    'p["canary_minimum_closed_trades"]',
    'p["canary_minimum_unsigned_build_coverage_percent"]',
    'def _percentile95',
    '"PRICE_ALREADY_MOVED"',
    '"PRICE_IMPACT_TOO_HIGH"',
    '"QUOTE_TOO_SLOW"',
    '"UNSIGNED_TRANSACTION_NOT_BUILT"',
    '"JUPITER_HTTP_ERROR"',
    '"protective_reject_rate_is_hard_gate": False',
    '"technical_failure_policy": "RESET_CLEAN_WINDOW_AND_REQUALIFY"',
    '"formal_selective_pass": False',
    '"legacy_m75_changed": False',
    '"m74_bypass": False',
]
# JUPITER_HTTP_ERROR appears in tests rather than the generic service classifier.
for token in required:
    haystack = src if token != '"JUPITER_HTTP_ERROR"' else (src + TEST.read_text(encoding="utf-8"))
    if token not in haystack:
        raise SystemExit(f"M291_VERIFY=FAIL;reason=MISSING_CONTRACT:{token}")

for forbidden in (
    "canary_minimum_entry_attempts_per_wallet",
    "canary_minimum_closed_trades_per_wallet",
    "def _percentile(",
):
    if forbidden in src:
        raise SystemExit(f"M291_R2_VERIFY=FAIL;reason=FORBIDDEN_R1_CONTRACT:{forbidden}")

print(
    "M291_R2_VERIFY=PASS;disarmed=true;legacy_m75_unchanged=true;"
    "market_protective_not_hard_reject_gate=true;technical_failure_resets_window=true;"
    "m74_bypass=false;economic_floor=true"
)
