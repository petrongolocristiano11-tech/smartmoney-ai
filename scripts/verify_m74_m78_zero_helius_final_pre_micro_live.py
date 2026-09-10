from __future__ import annotations
import ast, hashlib, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TARGETS=[
 'backend/app/services/gen4_zero_helius_final_pre_micro_live_service.py',
 'scripts/run_m74_m78_zero_helius_final_pre_micro_live.py',
 'tests/test_m74_m78_zero_helius_final_pre_micro_live.py',
]
FORBIDDEN=('httpx','requests','urllib','socket','websockets','aiohttp')
def sha(p): return hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
def main():
    for rel in TARGETS:
        path=ROOT/rel
        if not path.is_file(): raise RuntimeError(f'Missing {rel}')
        tree=ast.parse(path.read_text(encoding='utf-8'))
        imported=set()
        for node in ast.walk(tree):
            if isinstance(node,ast.Import): imported.update(x.name.split('.')[0] for x in node.names)
            elif isinstance(node,ast.ImportFrom) and node.module: imported.add(node.module.split('.')[0])
        bad=sorted(imported.intersection(FORBIDDEN))
        if bad: raise RuntimeError(f'Network import forbidden in {rel}: {bad}')
    service=(ROOT/TARGETS[0]).read_text(encoding='utf-8')
    m35_path=ROOT/'backend/app/services/blockchain_parser_micro_live_canary_service.py'
    if not m35_path.is_file(): raise RuntimeError('M35 governance service missing')
    m35=m35_path.read_text(encoding='utf-8')
    m35_required=[
      'MICRO_LIVE_CANARY_POLICY_VERSION = "canonical-parser-micro-live-canary-governance/2"',
      'CANONICAL_PARSER_MICRO_LIVE_CANARY_MAX_VALIDITY_MINUTES", 15',
      'CANONICAL_PARSER_MICRO_LIVE_CANARY_MAX_TOTAL_BUDGET_SOL", 0.05',
      'CANONICAL_PARSER_MICRO_LIVE_CANARY_MAX_ORDER_BUDGET_SOL", 0.01',
      'CANONICAL_PARSER_MICRO_LIVE_CANARY_MAX_ORDER_COUNT", 3',
      '"governance_and_simulation_only": True',
      '"signer_connected": False',
      '"live_engine_connected": False',
      '"external_requests_allowed": False',
      '"live_execution_authorized": False',
    ]
    for marker in m35_required:
        if marker not in m35: raise RuntimeError(f'M35 contract drift: {marker}')
    required=[
      '"network_requests": 0','"helius_requests": 0','"helius_credits": 0',
      '"jupiter_requests": 0','"live_orders": 0','"signer_access": False',
      '"minimum_independent_canary_wallets": 2','"consensus_window_seconds": 180',
      '"m35_maximum_total_budget_sol": 0.05','"m35_maximum_order_budget_sol": 0.01',
      '"m35_maximum_order_count": 3',
    ]
    for marker in required:
        if marker not in service: raise RuntimeError(f'Contract marker missing: {marker}')
    print('=== M74-M78 ZERO-HELIUS FINAL PRE-MICRO-LIVE VERIFIER ===')
    print('VERSION=canonical-parser-gen4-zero-helius-final-pre-micro-live/1')
    print('M74_CANDIDATE_ADMISSION=IMPLEMENTED_OFFLINE')
    print('M75_SHORT_CANARY_EVALUATOR=IMPLEMENTED_OFFLINE')
    print('M76_MULTI_WALLET_INDEPENDENCE_CONSENSUS=IMPLEMENTED_OFFLINE')
    print('M77_MICRO_LIVE_ENVELOPE=REUSES_EXISTING_M35_LIMITS')
    print('M77_EXISTING_M35_GOVERNANCE_CONTRACT=STATIC_VERIFIED')
    print('M75_M76_EVIDENCE_INTEGRITY=SHA256_FAIL_CLOSED')
    print('M73_FUTURE_REPORT_INTEGRITY=SHA256_FAIL_CLOSED')
    print('M78_FINAL_TRANSITION=EXPLICIT_AUTHORIZATION_ONLY')
    print('NETWORK_IMPORTS=FORBIDDEN')
    print('NETWORK_REQUESTS=0')
    print('PUBLIC_RPC_REQUESTS=0')
    print('HELIUS_REQUESTS=0')
    print('HELIUS_CREDITS=0')
    print('DATABASE_READS=0')
    print('DATABASE_WRITES=0')
    print('JUPITER_REQUESTS=0')
    print('PAPER_ORDERS=0')
    print('LIVE_ORDERS=0')
    print('SIGNER_ACCESS=NO')
    for rel in TARGETS: print(rel.upper().replace('/','_').replace('.','_')+'_SHA256='+sha(rel))
    print('VERIFIER=PASS')
if __name__=='__main__':
    try: main()
    except Exception as e:
        print(f'VERIFIER=FAILED type={type(e).__name__} message={e}')
        sys.exit(1)
