from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = Path.home() / "Downloads" / "smartmoney-audits"
RUN_CONFIRMATION = "EXECUTE_M73_DISCOVERY_TRANCHE_MAX_9000_HELIUS_CREDITS"
RECOVERY_CONFIRMATION = "RECOVER_M73_EXPANDED_AFTER_HOTFIX5_INTERRUPTED_EXACT_LOCK"
KNOWN_LOCK_SHA256 = "2897afff36d318876ed625e1924180c94bec1092fe7e5d39984f1646c9cc9342"
KNOWN_PLAN_PREFIX = "328abe2296e8b917"
EXPECTED = {
    "RUN_M66_CONTROLLED_HELIUS_DISCOVERY.ps1": "665e267616bf50ef45864490d26f0cf4d5c8a37db1490000bba63a78f9a0ea81",
    "backend/app/services/gen4_controlled_helius_discovery_service.py": "f4312154f95a9256c5a02e62dd4a100414d28c9ed3812159c9b3a75f23e5581a",
    "scripts/run_m66_controlled_helius_discovery.py": "21da3da6d63c49d4c1443091552f44fbbc302579f19db3a2973c639673096ec4",
    "backend/app/services/gen4_controlled_new_wallet_qualification_service.py": "eb2703fc5f93ef5dc76938c57653a99b64b6157c1be6ae2fc2d3c049a8f0caa8",
    "RUN_M73_CONTROLLED_NEW_WALLET_QUALIFICATION.ps1": "1af96bb9afb223d8d415563b9e76745d20206a12911b1624c65644480990e3f6",
    "scripts/run_m73_controlled_new_wallet_qualification.py": "c88b557e2cf6902805e21d8a8c13ac00c18f31ef838c57346729d77ee005ad57",
    "scripts/verify_m73_controlled_new_wallet_qualification.py": "e9578f4f966125a1eefbe07bc24c29865677688a10ad01689ed9ea9bc8f1002b",
}


def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    for rel, expected in EXPECTED.items():
        path=PROJECT_ROOT/rel
        if not path.is_file() or sha(path)!=expected:
            print(f"EXPANDED_DISCOVERY_PREFLIGHT=FAILED file={rel}")
            return 20
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    lock=AUDIT_DIR/f"smartmoney-m73-controlled-execution-lock-{KNOWN_PLAN_PREFIX}.json"
    if not lock.is_file() or sha(lock)!=KNOWN_LOCK_SHA256:
        print("EXPANDED_DISCOVERY_LOCK_PREFLIGHT=FAILED")
        return 21
    ps=None
    for name in ("powershell.exe", "pwsh.exe", "pwsh"):
        try:
            probe=subprocess.run([name,"-NoProfile","-Command","exit 0"],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        except OSError:
            continue
        if probe.returncode==0:
            ps=name; break
    if not ps:
        print("EXPANDED_DISCOVERY_POWERSHELL=FAILED")
        return 22
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log=AUDIT_DIR/f"smartmoney-m66-m73-expanded-discovery-tranche-{stamp}.txt"
    cmd=[
        ps,"-NoProfile","-ExecutionPolicy","Bypass","-File",
        str(PROJECT_ROOT/"RUN_M73_CONTROLLED_NEW_WALLET_QUALIFICATION.ps1"),
        "-ProjectRoot",str(PROJECT_ROOT),
        "-Confirmation",RUN_CONFIRMATION,
        "-RecoveryConfirmation",RECOVERY_CONFIRMATION,
        "-PublicRpcRequestCap","4000",
        "-MaximumCandidates","6",
        "-MaximumSignaturesPerCandidate","500",
    ]
    print("EXPANDED_DISCOVERY_TRANCHE=START")
    print("HELIUS_DEFAULT_PLANNED_MAX_REQUESTS=86")
    print("HELIUS_DEFAULT_PLANNED_MAX_CREDITS=8600")
    print("HELIUS_HARD_CAP_REQUESTS=90")
    print("HELIUS_HARD_CAP_CREDITS=9000")
    print("HELIUS_RETRIES=0")
    print("M66_PROVIDER_THROTTLE_SECONDS=0.15")
    print("M73_DEEP_CANDIDATES_DEFAULT=6")
    print("M73_DEEP_CANDIDATES_HARD_MAX=8")
    print("LIVE_AUTHORIZED=NO")
    print("SIGNER_AUTHORIZED=NO")
    seen=[]
    with log.open('w',encoding='utf-8',newline='\n') as out:
        out.write("COMMAND="+" ".join(cmd)+"\n")
        process=subprocess.Popen(
            cmd,cwd=PROJECT_ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            text=True,errors="replace",bufsize=1,
        )
        assert process.stdout is not None
        for raw in process.stdout:
            out.write(raw); out.flush()
            line=raw.strip(); seen.append(line)
            if (
                line.startswith(("M66_","M73_","NEW_","PRESCREEN_","CANDIDATES_","QUALIFIED_","OBSERVE_","RESEARCH_","REJECTED_","PUBLIC_RPC_","HELIUS_","OFFICIAL_","DATABASE_","LIVE_","SIGNER_"))
                or "FAILED" in line or "429" in line
            ):
                print(line)
        code=process.wait()
    if code!=0:
        print(f"EXPANDED_DISCOVERY_TRANCHE=FAILED exit_code={code}")
        print(f"LOG={log}")
        print("AUTO_RETRY=NO")
        return code or 1
    joined="\n".join(seen)
    required=(
        "M73_CONTROLLED_ACQUISITION_AND_QUALIFICATION=PASS",
        "M73_LOCK_RECOVERY_MODE=EXPANDED_EXACT_AFTER_HOTFIX5_INTERRUPTED_RUN",
        "M73_EXPANDED_AFTER_HOTFIX5_LOCK_RECOVERY=AUTHORIZED_EXACT_CURRENT_LOCK",
        "M73_HELIUS_MAXIMUM_REQUESTS=90",
        "M73_HELIUS_CREDIT_CAP=9000",
        "M73_HELIUS_RETRIES=0",
        "OFFICIAL_REALTIME_COUNTER=83_UNCHANGED",
        "LIVE_ORDERS=0",
        "SIGNER_AUTHORIZED=NO",
        "MICRO_LIVE_EXECUTION_AUTHORIZED=NO",
        "M73_REPORT_FILE=",
        "M73_REPORT_SHA256=",
    )
    missing=[item for item in required if item not in joined]
    if missing:
        print("EXPANDED_DISCOVERY_TRANCHE=FAILED_MISSING_MARKERS")
        print("MISSING="+",".join(missing))
        print(f"LOG={log}")
        return 23
    print("EXPANDED_DISCOVERY_TRANCHE=PASS")
    print(f"LOG={log}")
    print("NEXT=ANALYZE_M73_REPORT_AND_M74_ADMISSION")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
