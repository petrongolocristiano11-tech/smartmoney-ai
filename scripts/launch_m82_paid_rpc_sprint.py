from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(r"C:\smartmoney-ai")
RAILWAY_CMD = Path(r"C:\Users\petro\AppData\Roaming\npm\railway.cmd")
AUDIT_DIR = Path(r"C:\Users\petro\Downloads\smartmoney-audits")
RUNNER = PROJECT_ROOT / "scripts" / "run_m82_paid_rpc_sprint.py"
VERIFIER = PROJECT_ROOT / "scripts" / "verify_m82_paid_rpc_sprint.py"

M66 = AUDIT_DIR / "smartmoney-m66-controlled-helius-discovery-20260816T155111Z.json"
M79 = AUDIT_DIR / "smartmoney-m79-paid-candidate-zero-helius-triage-20260817T010349Z.json"
M80 = AUDIT_DIR / "smartmoney-m80-targeted-four-wallet-deep-qualification-20260817T024142Z.json"
M81_STATE = AUDIT_DIR / "smartmoney-m81-fast-discovery-state-20c2d5d2bb8ee3c5.json"

PORT = 55432
SERVICE = "smartmoney-ai"
DATABASE_SERVICE = "Postgres"
ENVIRONMENT = "production"
CONFIRMATION = "RUN_M82_PAID_RPC_SPRINT_MAX_9000_CREDITS"


class SafeStop(RuntimeError):
    pass


def railway_command(*args: str) -> list[str]:
    full = [str(RAILWAY_CMD), *args]
    return [
        os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"),
        "/d",
        "/s",
        "/c",
        subprocess.list2cmdline(full),
    ]


def port_open(host: str = "127.0.0.1", port: int = PORT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def load_railway_variables() -> dict[str, str]:
    proc = subprocess.run(
        railway_command(
            "variable",
            "list",
            "--service",
            SERVICE,
            "--environment",
            ENVIRONMENT,
            "--json",
        ),
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise SafeStop("RAILWAY_VARIABLE_READ=FAILED")
    raw = (proc.stdout or "").strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        raise SafeStop("RAILWAY_VARIABLE_JSON=NOT_FOUND")
    try:
        value = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise SafeStop("RAILWAY_VARIABLE_JSON=INVALID") from exc
    if not isinstance(value, dict):
        raise SafeStop("RAILWAY_VARIABLE_JSON=NOT_OBJECT")
    return {str(k): str(v) for k, v in value.items() if v is not None}


def build_local_database_url(private_url: str) -> str:
    parsed = make_url(private_url)
    if not parsed.drivername or not parsed.host:
        raise SafeStop("DATABASE_URL=INVALID")
    return parsed.set(host="127.0.0.1", port=PORT).render_as_string(
        hide_password=False
    )


def start_tunnel_if_needed():
    if port_open():
        print("DB_TUNNEL=ALREADY_OPEN", flush=True)
        return None, None, None

    print("DB_TUNNEL=STARTING", flush=True)
    stdout_log = Path(tempfile.gettempdir()) / "smartmoney-m82-tunnel.out"
    stderr_log = Path(tempfile.gettempdir()) / "smartmoney-m82-tunnel.err"
    for path in (stdout_log, stderr_log):
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    out_handle = stdout_log.open("w", encoding="utf-8")
    err_handle = stderr_log.open("w", encoding="utf-8")
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(
        railway_command(
            "connect",
            DATABASE_SERVICE,
            "--environment",
            ENVIRONMENT,
            "--tunnel-only",
            "--port",
            str(PORT),
        ),
        cwd=str(PROJECT_ROOT),
        stdout=out_handle,
        stderr=err_handle,
        text=True,
        creationflags=creationflags,
    )
    for _ in range(40):
        if proc.poll() is not None:
            out_handle.close()
            err_handle.close()
            raise SafeStop("DB_TUNNEL=FAILED")
        if port_open():
            print("DB_TUNNEL=PASS", flush=True)
            return proc, out_handle, err_handle
        time.sleep(0.25)
    try:
        proc.terminate()
    except Exception:
        pass
    out_handle.close()
    err_handle.close()
    raise SafeStop("DB_TUNNEL=TIMEOUT")


def cleanup_tunnel(proc, out_handle, err_handle) -> None:
    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    for handle in (out_handle, err_handle):
        if handle is not None:
            try:
                handle.close()
            except Exception:
                pass
    for name in ("smartmoney-m82-tunnel.out", "smartmoney-m82-tunnel.err"):
        path = Path(tempfile.gettempdir()) / name
        try:
            path.unlink()
        except (FileNotFoundError, OSError):
            pass


def main() -> int:
    print("=== SMARTMONEY M82 SAFE LAUNCHER ===", flush=True)
    print("POWERSHELL_EXIT_COMMANDS=NONE", flush=True)
    print("PARSER_STABLECOIN_HARDENING=REQUIRED", flush=True)
    print("HELIUS_RPC_PACKAGE_CREDIT_CAP=9000", flush=True)
    print("LIVE_AUTHORIZED=NO", flush=True)
    print("SIGNER_AUTHORIZED=NO", flush=True)
    print("OUTPUT_HEARTBEAT_SECONDS=5", flush=True)
    print("", flush=True)

    if os.name != "nt":
        raise SafeStop("OS=NOT_WINDOWS")
    expected_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if Path(sys.executable).resolve() != expected_python.resolve():
        raise SafeStop(f"PYTHON=WRONG;USE={expected_python}")
    if not RAILWAY_CMD.is_file():
        raise SafeStop(f"RAILWAY_CMD=MISSING:{RAILWAY_CMD}")

    for path in (RUNNER, VERIFIER, M66, M79, M80, M81_STATE):
        if not path.is_file():
            raise SafeStop(f"FILE_MISSING={path}")

    verify = subprocess.run(
        [sys.executable, str(VERIFIER)],
        cwd=str(PROJECT_ROOT),
        check=False,
    )
    if verify.returncode != 0:
        raise SafeStop("M82_VERIFIER=FAILED")
    print("M82_VERIFIER=PREFLIGHT_PASS", flush=True)

    tunnel_proc = None
    out_handle = None
    err_handle = None
    try:
        tunnel_proc, out_handle, err_handle = start_tunnel_if_needed()
        variables = load_railway_variables()
        for name in ("DATABASE_URL", "SOLANA_RPC_URL", "HELIUS_API_KEY"):
            if not variables.get(name, "").strip():
                raise SafeStop(f"{name}=ABSENT")
            print(f"{name}=PRESENT", flush=True)

        local_db = build_local_database_url(variables["DATABASE_URL"])
        print("LOCAL_DATABASE_URL=BUILT", flush=True)

        env = os.environ.copy()
        env["DATABASE_URL"] = local_db
        env["SOLANA_RPC_URL"] = variables["SOLANA_RPC_URL"]
        env["HELIUS_API_KEY"] = variables["HELIUS_API_KEY"]
        env["ENVIRONMENT"] = "production"
        env["RAW_BLOCKCHAIN_CAPTURE_ENABLED"] = "false"

        for name in (
            "HELIUS_CREDIT_GUARD_ENABLED",
            "HELIUS_CREDIT_GUARD_ENFORCE_IN_NON_PRODUCTION",
            "HELIUS_APP_DAILY_CREDIT_CAP",
            "HELIUS_ENHANCED_DAILY_CREDIT_CAP",
            "HELIUS_RPC_DAILY_CREDIT_CAP",
            "HELIUS_REQUEST_TIMEOUT_SECONDS",
            "HELIUS_MAX_RETRIES",
            "HELIUS_RETRY_BASE_SECONDS",
            "HELIUS_RETRY_MAX_SECONDS",
        ):
            value = variables.get(name)
            if value is not None and value.strip():
                env[name] = value

        args = [
            sys.executable,
            str(RUNNER),
            "--confirmation",
            CONFIRMATION,
            "--output-dir",
            str(AUDIT_DIR),
            "--m66-report",
            str(M66),
            "--m79-report",
            str(M79),
            "--m80-report",
            str(M80),
            "--m81-state",
            str(M81_STATE),
        ]
        print("", flush=True)
        print("M82_RUNTIME_CONFIGURATION=PASS", flush=True)
        print("STARTING_M82_NOW=YES", flush=True)
        print("", flush=True)
        result = subprocess.run(
            args,
            cwd=str(PROJECT_ROOT),
            env=env,
            check=False,
        )
        print("", flush=True)
        print(f"M82_RUNTIME_EXIT_CODE={result.returncode}", flush=True)
        print(
            "M82_RUNTIME_COMMAND="
            + ("PASS" if result.returncode == 0 else "FAILED"),
            flush=True,
        )
        return int(result.returncode)
    finally:
        cleanup_tunnel(tunnel_proc, out_handle, err_handle)


if __name__ == "__main__":
    try:
        code = main()
    except SafeStop as exc:
        print("", flush=True)
        print(f"SAFE_STOP={exc}", flush=True)
        print("M82_RUNTIME_STARTED=NO", flush=True)
        code = 2
    except KeyboardInterrupt:
        print("", flush=True)
        print("INTERRUPTED=YES", flush=True)
        print(
            "M82 usa cache per-richiesta e state checkpoint: non cancellare cache/state.",
            flush=True,
        )
        code = 130
    except Exception as exc:
        print("", flush=True)
        print(
            f"LAUNCHER_FAILED={type(exc).__name__}:{' '.join(str(exc).split())[:300]}",
            flush=True,
        )
        print("NON_RILANCIARE_ALLA_CIECA.", flush=True)
        code = 3

    # Exits only this external Python process; PowerShell remains open.
    sys.exit(code)
