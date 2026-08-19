from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.gen4_zero_helius_final_pre_micro_live_service import (
    M74M78Error,
    M74_M78_EVALUATE_CONFIRMATION,
    M74_M78_PREPARE_CONFIRMATION,
    build_preparation_report,
    evaluate_post_discovery,
    validate_report,
)

def sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open('rb') as fh:
        for chunk in iter(lambda: fh.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def write_json_atomic(path: Path, value: Any) -> None:
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8')
    tmp.replace(path)

def load(path_text: str, label: str) -> tuple[Path, dict[str, Any]]:
    path = Path(path_text).expanduser().resolve()
    if not path.is_file(): raise M74M78Error(f'{label} non trovato: {path.name}.')
    try: value = json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception as exc: raise M74M78Error(f'{label} non leggibile: {path.name}.') from exc
    if not isinstance(value, dict): raise M74M78Error(f'{label} root non oggetto.')
    return path, value

def outside_project(path: Path) -> bool:
    try: path.relative_to(PROJECT_ROOT); return False
    except ValueError: return True

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='M74-M78 final pre-Micro-Live control plane, zero network.')
    p.add_argument('--mode', choices=['prepare','evaluate'], default='prepare')
    p.add_argument('--confirmation', required=True)
    p.add_argument('--output-dir', required=True)
    p.add_argument('--m72-report', required=True)
    p.add_argument('--m72-plan', required=True)
    p.add_argument('--m73-report', default='')
    p.add_argument('--canary-evidence', default='')
    p.add_argument('--independence-evidence', default='')
    return p

def main() -> int:
    args = parser().parse_args()
    output = Path(args.output_dir).expanduser().resolve()
    if not outside_project(output): raise M74M78Error('Output M74-M78 deve restare fuori dal repository.')
    output.mkdir(parents=True, exist_ok=True)
    m72_path, m72 = load(args.m72_report, 'Report M72')
    plan_path, plan = load(args.m72_plan, 'Piano M72')
    now = datetime.now(timezone.utc)
    if args.mode == 'prepare':
        if args.confirmation != M74_M78_PREPARE_CONFIRMATION: raise M74M78Error(f'Conferma richiesta: {M74_M78_PREPARE_CONFIRMATION}.')
        report = build_preparation_report(m72, plan, prepared_at=now)
        prefix = 'smartmoney-m74-m78-zero-helius-final-prep'
    else:
        if args.confirmation != M74_M78_EVALUATE_CONFIRMATION: raise M74M78Error(f'Conferma richiesta: {M74_M78_EVALUATE_CONFIRMATION}.')
        _, m73 = load(args.m73_report, 'Report M73')
        _, canary = load(args.canary_evidence, 'Evidenza canary')
        _, independence = load(args.independence_evidence, 'Evidenza indipendenza')
        report = evaluate_post_discovery(m72, plan, m73, canary, independence, evaluated_at=now)
        prefix = 'smartmoney-m74-m78-post-discovery-evaluation'
    validate_report(report)
    path = output / f'{prefix}-{now.strftime("%Y%m%dT%H%M%SZ")}.json'
    write_json_atomic(path, report)
    transition = dict(report.get('m78_final_transition') or {})
    print('=== M74-M78 ZERO-HELIUS FINAL PRE-MICRO-LIVE ===')
    print('M74_M78=PASS')
    print(f'MODE={args.mode.upper()}')
    print(f'INPUT_M72_REPORT_SHA256={sha256_file(m72_path)}')
    print(f'INPUT_M72_PLAN_SHA256={sha256_file(plan_path)}')
    print('NETWORK_REQUESTS=0')
    print('PUBLIC_RPC_REQUESTS=0')
    print('HELIUS_REQUESTS=0')
    print('HELIUS_CREDITS=0')
    print('DATABASE_READS=0')
    print('DATABASE_WRITES=0')
    print('JUPITER_REQUESTS=0')
    print('PAPER_ORDERS=0')
    print('LIVE_ORDERS=0')
    print('SIGNED_TRANSACTIONS=0')
    print('SUBMITTED_TRANSACTIONS=0')
    print('SIGNER_ACCESS=NO')
    print('AUTOMATIC_LIVE_ACTIVATION=NO')
    print('MICRO_LIVE_EXECUTION_AUTHORIZED=NO')
    if args.mode == 'prepare':
        print('CURRENT_STATE=AWAITING_HELIUS_RENEWAL_AND_NEW_WALLET_DISCOVERY')
        print('M74_CANDIDATE_ADMISSION=IMPLEMENTED')
        print('M75_SHORT_CANARY=IMPLEMENTED_DISARMED')
        print('M76_MULTI_WALLET_CONSENSUS=IMPLEMENTED_DISARMED')
        print('M77_MICRO_LIVE_ENVELOPE=IMPLEMENTED_DISARMED_REUSES_M35')
        print('M78_FINAL_TRANSITION=IMPLEMENTED_AWAITING_REAL_EVIDENCE')
    else:
        print('MICRO_LIVE_READY=' + ('YES' if transition.get('micro_live_ready') else 'NO'))
        print(f'FINAL_STATE={transition.get("state")}')
        print(f'QUALIFIED_WALLETS={transition.get("qualified_wallets",0)}')
        print(f'SHORT_CANARY_PASS_WALLETS={transition.get("short_canary_pass_wallets",0)}')
    print(f'M74_M78_REPORT_FILE={path}')
    print(f'M74_M78_REPORT_SHA256={sha256_file(path)}')
    return 0

if __name__ == '__main__':
    try: raise SystemExit(main())
    except Exception as error:
        message = ' '.join(str(error).split()) or 'Nessun dettaglio disponibile.'
        print(f'M74_M78=FAILED type={type(error).__name__} message={message}')
        raise SystemExit(1) from None
