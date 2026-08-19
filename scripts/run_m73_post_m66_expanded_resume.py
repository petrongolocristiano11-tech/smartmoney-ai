from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = Path.home() / "Downloads" / "smartmoney-audits"

RUN_CONFIRMATION = "EXECUTE_M73_DISCOVERY_TRANCHE_MAX_9000_HELIUS_CREDITS"
RECOVERY_CONFIRMATION = "RESUME_M73_AFTER_M66_EXPANDED_POLICY_FAILURE_EXACT_ARTIFACTS"
KNOWN_PLAN_PREFIX = "328abe2296e8b917"
KNOWN_CURRENT_LOCK_SHA256 = "1f6d6d3c73e3fcbc32f99482aa4b70fe0be6f3f89144c06a476e4dcef61ad99c"
KNOWN_M66_REPORT_NAME = "smartmoney-m66-controlled-helius-discovery-20260816T155111Z.json"
KNOWN_M66_REPORT_SHA256 = "b2ba27bfef29e6628f0a865f7e16fc35147e9430131278432ff68a756ffc1080"
KNOWN_M66_CACHE_NAME = "smartmoney-m66-helius-request-cache-20260816T155111Z.json"
KNOWN_M66_CACHE_SHA256 = "0cab70ecee5d437bff83729337be2db547ff2f2680cb069d98540c78b9211c31"
KNOWN_FAILED_LOG_NAME = "smartmoney-m66-m73-expanded-discovery-tranche-20260816T154757Z.txt"
KNOWN_FAILED_LOG_SHA256 = "e58a5cf61785d30c89334c81fc1ab0f1279577837fbc7bd6a7204e6eda66568f"

EXPECTED = {
    "RUN_M66_CONTROLLED_HELIUS_DISCOVERY.ps1": "665e267616bf50ef45864490d26f0cf4d5c8a37db1490000bba63a78f9a0ea81",
    "backend/app/services/gen4_controlled_helius_discovery_service.py": "f4312154f95a9256c5a02e62dd4a100414d28c9ed3812159c9b3a75f23e5581a",
    "scripts/run_m66_controlled_helius_discovery.py": "21da3da6d63c49d4c1443091552f44fbbc302579f19db3a2973c639673096ec4",
    "backend/app/services/gen4_zero_helius_pre_micro_live_service.py": "ce124eb5648676faa275dd75a7777c27c6ce3878a2af6e810908710d1447cfa7",
    "scripts/run_m67_m70_zero_helius_pre_micro_live.py": "549d08c98cff48be9dbe8bc7582935daa1db4c361a87c0cca793350b9eda44d7",
    "backend/app/services/gen4_controlled_new_wallet_qualification_service.py": "eb2703fc5f93ef5dc76938c57653a99b64b6157c1be6ae2fc2d3c049a8f0caa8",
    "RUN_M73_CONTROLLED_NEW_WALLET_QUALIFICATION.ps1": "1af96bb9afb223d8d415563b9e76745d20206a12911b1624c65644480990e3f6",
    "scripts/run_m73_controlled_new_wallet_qualification.py": "c88b557e2cf6902805e21d8a8c13ac00c18f31ef838c57346729d77ee005ad57",
}


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    for rel, expected in EXPECTED.items():
        path = PROJECT_ROOT / rel
        if not path.is_file() or sha(path) != expected:
            print(f"M73_POST_M66_RESUME_PREFLIGHT=FAILED file={rel}")
            return 20

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    exact_files = (
        (
            AUDIT_DIR / f"smartmoney-m73-controlled-execution-lock-{KNOWN_PLAN_PREFIX}.json",
            KNOWN_CURRENT_LOCK_SHA256,
            "LOCK",
        ),
        (AUDIT_DIR / KNOWN_M66_REPORT_NAME, KNOWN_M66_REPORT_SHA256, "M66_REPORT"),
        (AUDIT_DIR / KNOWN_M66_CACHE_NAME, KNOWN_M66_CACHE_SHA256, "M66_CACHE"),
        (AUDIT_DIR / KNOWN_FAILED_LOG_NAME, KNOWN_FAILED_LOG_SHA256, "FAILED_LOG"),
    )
    for path, expected, label in exact_files:
        if not path.is_file() or sha(path) != expected:
            print(f"M73_POST_M66_RESUME_{label}_PREFLIGHT=FAILED")
            return 21

    ps = None
    for name in ("powershell.exe", "pwsh.exe", "pwsh"):
        try:
            probe = subprocess.run(
                [name, "-NoProfile", "-Command", "exit 0"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            continue
        if probe.returncode == 0:
            ps = name
            break
    if not ps:
        print("M73_POST_M66_RESUME_POWERSHELL=FAILED")
        return 22

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log = AUDIT_DIR / f"smartmoney-m73-post-m66-resume-{stamp}.txt"
    cmd = [
        ps,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(PROJECT_ROOT / "RUN_M73_CONTROLLED_NEW_WALLET_QUALIFICATION.ps1"),
        "-ProjectRoot",
        str(PROJECT_ROOT),
        "-Confirmation",
        RUN_CONFIRMATION,
        "-RecoveryConfirmation",
        RECOVERY_CONFIRMATION,
        "-PublicRpcRequestCap",
        "4000",
        "-MaximumCandidates",
        "6",
        "-MaximumSignaturesPerCandidate",
        "500",
    ]

    print("M73_POST_M66_RESUME=START")
    print("M66_REEXECUTION_AUTHORIZED=NO")
    print("NEW_HELIUS_REQUESTS_AUTHORIZED=0")
    print("NEW_HELIUS_CREDITS_AUTHORIZED=0")
    print("REUSE_M66_REQUESTS=77")
    print("REUSE_M66_CREDITS=7700")
    print("REUSE_M66_NEW_WALLETS=374")
    print("REUSE_M66_PRESCREENED=70")
    print("REUSE_M66_PRESCREEN_PASS=27")
    print("M73_DEEP_CANDIDATES=6")
    print("M73_PUBLIC_RPC_CAP=4000")
    print("LIVE_AUTHORIZED=NO")
    print("SIGNER_AUTHORIZED=NO")

    seen: list[str] = []
    with log.open("w", encoding="utf-8", newline="\n") as out:
        out.write("COMMAND=" + " ".join(cmd) + "\n")
        process = subprocess.Popen(
            cmd,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            bufsize=1,
        )
        assert process.stdout is not None
        for raw in process.stdout:
            out.write(raw)
            out.flush()
            line = raw.strip()
            seen.append(line)
            if (
                line.startswith(
                    (
                        "M73_",
                        "NEW_",
                        "CANDIDATES_",
                        "QUALIFIED_",
                        "OBSERVE_",
                        "RESEARCH_",
                        "REJECTED_",
                        "PUBLIC_RPC_",
                        "OFFICIAL_",
                        "DATABASE_",
                        "LIVE_",
                        "SIGNER_",
                    )
                )
                or "FAILED" in line
            ):
                print(line)
        code = process.wait()

    print(f"M73_POST_M66_RESUME_LOG={log}")
    if code != 0:
        print(f"M73_POST_M66_RESUME=FAILED exit_code={code}")
        print("M66_REEXECUTION=NO")
        print("AUTO_RETRY=NO")
        return code or 1

    joined = "\n".join(seen)
    required = (
        "M73_CONTROLLED_ACQUISITION_AND_QUALIFICATION=PASS",
        "M73_LOCK_RECOVERY_MODE=POST_M66_EXACT_ARTIFACT_RESUME_ZERO_NEW_HELIUS",
        "M73_POST_M66_EXACT_RESUME=AUTHORIZED_SKIP_M66_ZERO_NEW_HELIUS",
        "M73_M66_RESUME_MODE=EXACT_EXISTING_M66_ARTIFACTS_ZERO_NEW_HELIUS",
        "M73_M66_INVOKED=NO",
        "M73_NEW_HELIUS_REQUESTS=0",
        "M73_NEW_HELIUS_CREDITS=0",
        "M73_M66_PRESCREEN_PASS_CANDIDATES=27",
        "CANDIDATES_DEEP_ANALYZED=6",
        "OFFICIAL_REALTIME_COUNTER=83_UNCHANGED",
        "LIVE_ORDERS=0",
        "SIGNER_AUTHORIZED=NO",
        "MICRO_LIVE_EXECUTION_AUTHORIZED=NO",
        "M73_REPORT_FILE=",
        "M73_REPORT_SHA256=",
    )
    missing = [marker for marker in required if marker not in joined]
    if missing:
        print("M73_POST_M66_RESUME_MARKERS=FAILED missing=" + ",".join(missing))
        return 23

    expected_selection = (
        "M73_SELECTED_DEEP_WALLETS="
        "6onSjcGDusjeU5phv7pDQS5srQBwNcyrd4ntKmeNBySm,"
        "BXryySjtoLsVCPeqrhZDj9nHSHkjvpevEpRgBzGa1NRm,"
        "EyUe9QvXGbMHAjKisjrb5qaem3dWQVUxhA1DgE2HtnVC,"
        "FEnytBSi3X86gAMCqHtsoWHavtiij2hGyuFKPbSNwZAC,"
        "TH5KpPyqJ8SBE9Sya7YVzY8217MQGmjrjgG9WusW4M7,"
        "2GFVxYeK7JR9mdNFjbqT1tiZkNaK6R386k6Rb7Bvauov"
    )
    if expected_selection not in joined:
        print("M73_POST_M66_RESUME_SELECTION=FAILED")
        return 24

    print("M73_POST_M66_RESUME_SELECTION=PASS_TOP6_PRESCREEN")
    print("M73_POST_M66_RESUME=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
