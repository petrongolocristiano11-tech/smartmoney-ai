from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

PROJECT = Path(r"C:\smartmoney-ai")
AUDIT = Path.home() / "Downloads" / "smartmoney-audits"
EXPECTED_HEAD = "40523857dae53a7b3f9c00160d1258fa4eb48ea8"
RAILWAY_SERVICE = "smartmoney-ai"
RAILWAY_DB_SERVICE = "Postgres"
RAILWAY_ENV = "production"
CONFIRM = "COLLECT_M299_POST_ANCHOR_READONLY"

M297_REPORT = AUDIT / "smartmoney-m297-r3-six-wallet-clean-forward-anchor-40523857dae5.json"
M297_SHA = "0f1c033d7c4cc02d38e292970b3e334a5a665aee81e963bcd0727602ab7e4bf5"
M298_REPORT = AUDIT / "smartmoney-m298-pre-selective-readiness-contract-40523857dae5.json"
M298_SHA = "22be261b8af2a260cc253b7b71d50ccd876aa2894cb9d27082d968ca9d34c962"

sys.path.insert(0, str(PROJECT))

from backend.app.services.gen4_post_anchor_selective_evidence_service import (
    CHALLENGER_WALLETS,
    M297_ANCHOR_UTC,
    OFFICIAL_WALLETS,
    build_acquisition_report,
    build_challenger_progress,
    build_official_wallet_evidence,
    sign_m298_evidence_from_acquisition,
    validate_acquisition_report,
)


class Stop(RuntimeError):
    pass


def safe(v: Any, n: int = 1800) -> str:
    return str(v or "").replace("\r", " ").replace("\n", " ")[:n]


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd, timeout=90, binary=False):
    p = subprocess.run(
        cmd, cwd=str(PROJECT), capture_output=True,
        text=not binary, timeout=timeout, check=False
    )
    if p.returncode:
        out = (
            ((p.stderr or b"") + (p.stdout or b"")).decode("utf-8", "replace")
            if binary else (p.stderr or p.stdout)
        )
        raise Stop("M299_COMMAND_FAILED:" + safe(out))
    return p.stdout


def win_cmd(exe: Path, *args: str):
    full = [str(exe), *args]
    if str(exe).lower().endswith((".cmd", ".bat")):
        return [
            os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"),
            "/d", "/s", "/c", subprocess.list2cmdline(full),
        ]
    return full


def railway_path() -> Path:
    for p in (
        Path.home() / "AppData/Roaming/npm/railway.cmd",
        Path(r"C:\Users\petro\AppData\Roaming\npm\railway.cmd"),
    ):
        if p.is_file():
            return p
    raise Stop("M299_RAILWAY_NOT_FOUND")


def railway_json(rail: Path, args: list[str]):
    text = run(win_cmd(rail, *args), 60)
    starts = [x for x in (text.find("{"), text.find("[")) if x >= 0]
    if not starts:
        raise Stop("M299_RAILWAY_JSON_INVALID")
    try:
        return json.loads(text[min(starts):])
    except json.JSONDecodeError as exc:
        raise Stop("M299_RAILWAY_JSON_PARSE_FAILED:" + safe(exc)) from exc


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=.35):
            return True
    except OSError:
        return False


def choose_port() -> int:
    for p in range(55432, 55472):
        if not port_open(p):
            return p
    raise Stop("M299_NO_FREE_PORT")


def cleanup(proc, handles, paths):
    if proc:
        try:
            proc.terminate()
            proc.wait(5)
        except Exception:
            try:
                proc.kill()
                proc.wait(5)
            except Exception:
                pass
    for h in handles:
        try:
            h.close()
        except Exception:
            pass
    for p in paths:
        try:
            p.unlink()
        except Exception:
            pass


def tunnel(rail: Path, port: int):
    out = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix="m299-db-", suffix=".out", delete=False
    )
    err = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", prefix="m299-db-", suffix=".err", delete=False
    )
    proc = subprocess.Popen(
        win_cmd(
            rail, "connect", RAILWAY_DB_SERVICE,
            "--environment", RAILWAY_ENV,
            "--tunnel-only", "--port", str(port)
        ),
        cwd=str(PROJECT),
        stdout=out,
        stderr=err,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    for _ in range(80):
        if proc.poll() is not None:
            cleanup(proc, [out, err], [Path(out.name), Path(err.name)])
            raise Stop("M299_DB_TUNNEL_FAILED")
        if port_open(port):
            return proc, [out, err], [Path(out.name), Path(err.name)]
        time.sleep(.25)
    cleanup(proc, [out, err], [Path(out.name), Path(err.name)])
    raise Stop("M299_DB_TUNNEL_TIMEOUT")


def local_url(private: str, port: int) -> str:
    from sqlalchemy.engine import make_url
    u = make_url(private)
    return u.set(
        drivername="postgresql",
        host="127.0.0.1",
        port=port,
    ).render_as_string(hide_password=False)


def lineage_preflight():
    if not M297_REPORT.is_file() or sha_file(M297_REPORT) != M297_SHA:
        raise Stop("M299_M297_REPORT_INVALID")
    if not M298_REPORT.is_file() or sha_file(M298_REPORT) != M298_SHA:
        raise Stop("M299_M298_REPORT_INVALID")
    m297 = json.loads(M297_REPORT.read_text(encoding="utf-8-sig"))
    if str(m297.get("anchor_utc") or "") != M297_ANCHOR_UTC:
        raise Stop("M299_M297_ANCHOR_MISMATCH")


def owner_campaign(active_rows, wallet: str):
    owners = []
    for row in active_rows:
        wallets = {str(x) for x in (row.get("frozen_wallets") or [])}
        if wallet in wallets:
            owners.append(row)
    if len(owners) != 1:
        raise Stop(f"M299_CAMPAIGN_OWNER_CARDINALITY:{wallet}:{len(owners)}")
    return owners[0]


def collect(confirm: str):
    if confirm != CONFIRM:
        raise Stop("M299_EXPLICIT_CONFIRMATION_REQUIRED")
    lineage_preflight()
    rail = railway_path()

    deployments = railway_json(
        rail,
        ["deployment", "list", "--service", RAILWAY_SERVICE,
         "--environment", RAILWAY_ENV, "--limit", "20", "--json"],
    )
    successful = []
    for row in deployments if isinstance(deployments, list) else []:
        meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
        if str(row.get("status") or "").upper() == "SUCCESS":
            successful.append(str(meta.get("commitHash") or "").strip().lower())
    if not successful or successful[0] != EXPECTED_HEAD:
        raise Stop("M299_DEPLOYED_HEAD_MISMATCH")

    vars_obj = railway_json(
        rail,
        ["variable", "list", "--service", RAILWAY_SERVICE,
         "--environment", RAILWAY_ENV, "--json"],
    )
    if not isinstance(vars_obj, dict):
        raise Stop("M299_VARIABLE_LIST_INVALID")
    private = str(
        vars_obj.get("DATABASE_PRIVATE_URL")
        or vars_obj.get("DATABASE_URL")
        or ""
    ).strip()
    if not private:
        raise Stop("M299_DATABASE_URL_MISSING")

    from psycopg import connect
    from psycopg.rows import dict_row

    anchor = datetime.fromisoformat(M297_ANCHOR_UTC)
    terminal = datetime.now(timezone.utc)
    query_count = 0
    proc = None
    handles = []
    paths = []

    try:
        port = choose_port()
        proc, handles, paths = tunnel(rail, port)
        conn = connect(local_url(private, port), row_factory=dict_row, autocommit=False)
        cur = conn.cursor()
        cur.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cur.execute("SHOW transaction_read_only")
        query_count += 1
        if str(cur.fetchone()["transaction_read_only"]).lower() not in {"on", "true"}:
            raise Stop("M299_DB_NOT_READ_ONLY")

        cur.execute(
            """
            SELECT *
            FROM canonical_parser_gen4_copyability_campaigns
            WHERE status='ACTIVE'
            ORDER BY started_at,id
            """
        )
        query_count += 1
        active = [dict(x) for x in cur.fetchall()]

        official_results = {}
        for label, wallet in OFFICIAL_WALLETS.items():
            campaign_row = owner_campaign(active, wallet)
            cid = str(campaign_row["campaign_id"])
            campaign_db_id = int(campaign_row["id"])

            cur.execute(
                """
                SELECT *
                FROM canonical_parser_gen4_fastpath_shadow_events
                WHERE wallet_address=%s
                  AND campaign_id=%s
                  AND fast_received_at > %s
                ORDER BY fast_received_at,id
                """,
                (wallet, cid, anchor),
            )
            query_count += 1
            events = [dict(x) for x in cur.fetchall()]

            cur.execute(
                """
                SELECT *
                FROM canonical_parser_gen4_fastpath_selective_positions
                WHERE wallet_address=%s
                  AND campaign_id=%s
                  AND entry_received_at > %s
                ORDER BY entry_received_at,id
                """,
                (wallet, cid, anchor),
            )
            query_count += 1
            positions = [dict(x) for x in cur.fetchall()]

            signatures = [
                str(x.get("signature") or "")
                for x in events
                if str(x.get("signature") or "")
            ]
            receipts = []
            if signatures:
                cur.execute(
                    """
                    SELECT *
                    FROM canonical_parser_gen4_webhook_receipts
                    WHERE campaign_db_id=%s
                      AND source='WEBHOOK'
                      AND signature=ANY(%s)
                    ORDER BY received_at,id
                    """,
                    (campaign_db_id, signatures),
                )
                query_count += 1
                receipts = [dict(x) for x in cur.fetchall()]

            official_results[label] = build_official_wallet_evidence(
                wallet=wallet,
                events=events,
                positions=positions,
                receipts=receipts,
                campaign=SimpleNamespace(**campaign_row),
                anchor_utc=anchor,
                terminal_at=terminal,
            )

        challenger_results = {}
        for label, wallet in CHALLENGER_WALLETS.items():
            cur.execute(
                """
                SELECT *
                FROM canonical_parser_gen4_fastpath_shadow_events
                WHERE wallet_address=%s
                  AND fast_received_at > %s
                ORDER BY fast_received_at,id
                """,
                (wallet, anchor),
            )
            query_count += 1
            events = [dict(x) for x in cur.fetchall()]
            challenger_results[label] = build_challenger_progress(
                wallet=wallet,
                events=events,
                anchor_utc=anchor,
                terminal_at=terminal,
            )

        conn.rollback()
        conn.close()
    finally:
        cleanup(proc, handles, paths)

    acquisition_safety = {
        "database_transaction": "REPEATABLE_READ_READ_ONLY",
        "database_select_statements": query_count,
        "database_writes": 0,
        "railway_cli_reads": 2,
        "railway_variable_set": False,
        "network_accessed_for_readonly_acquisition": True,
        "provider_history_calls": 0,
        "helius_calls": 0,
        "helius_credits": 0,
        "birdeye_cu": 0,
        "jupiter_requests": 0,
        "backend_mutations": 0,
        "live": False,
        "signer": False,
        "submitted_transactions": 0,
        "paper_orders": 0,
        "commit": False,
        "push": False,
        "deploy": False,
    }

    acquisition = build_acquisition_report(
        official_results=official_results,
        challenger_results=challenger_results,
        acquired_at=terminal,
        acquisition_safety=acquisition_safety,
    )
    validate_acquisition_report(acquisition)

    AUDIT.mkdir(parents=True, exist_ok=True)
    stamp = terminal.strftime("%Y%m%dT%H%M%SZ")
    raw_path = AUDIT / f"smartmoney-m299-post-anchor-acquisition-{stamp}.json"
    raw_bytes = json.dumps(acquisition, indent=2, sort_keys=True, default=str).encode("utf-8")
    raw_path.write_bytes(raw_bytes)
    raw_sha = hashlib.sha256(raw_bytes).hexdigest()

    # Offline transform phase: no further DB/network action after acquisition is built.
    signed = sign_m298_evidence_from_acquisition(acquisition)
    evidence_path = AUDIT / f"smartmoney-m299-selective-evidence-{stamp}.json"
    evidence_bytes = json.dumps(signed, indent=2, sort_keys=True, default=str).encode("utf-8")
    evidence_path.write_bytes(evidence_bytes)
    evidence_sha = hashlib.sha256(evidence_bytes).hexdigest()

    print(f"M299_ACQUIRED_AT_UTC={terminal.isoformat()}")
    print(f"M299_DB_TX=PASS;read_only=true;select_statements={query_count};writes=0")
    for label, result in official_results.items():
        row = dict(result["wallet_evidence"])
        evaluation = dict(result["m298_individual_evaluation"])
        print(
            "M299_OFFICIAL;"
            f"label={label};attempts={row['entry_attempts']};"
            f"accepted={row['accepted_attempts']};protective={row['protective_rejects']};"
            f"technical={row['technical_failures']};closed={row['closed_trades']};"
            f"net={row['net_pnl_sol']:.9f};pf={row['profit_factor']:.6f};"
            f"dd={row['maximum_drawdown_percent']:.6f};"
            f"m298_pass={str(bool(evaluation.get('passed'))).lower()};"
            f"effective_anchor={row['m299_metadata']['effective_clean_anchor_utc']}"
        )
    for label, row in challenger_results.items():
        print(
            "M299_CHALLENGER;"
            f"label={label};attempts={row['entry_attempts']};"
            f"accepted={row['accepted_attempts']};protective={row['protective_rejects']};"
            f"technical={row['technical_failures']};"
            "full_lifecycle_claimed=false;selective_evidence_eligible=false"
        )

    print(f"M299_ACQUISITION_REPORT={raw_path}")
    print(f"M299_ACQUISITION_REPORT_SHA256={raw_sha}")
    print(f"M299_SELECTIVE_EVIDENCE={evidence_path}")
    print(f"M299_SELECTIVE_EVIDENCE_SHA256={evidence_sha}")
    print(
        "M299_SAFETY=PASS;db_read_only=true;db_writes=0;"
        "helius_calls=0;birdeye_cu=0;jupiter_requests=0;backend_mutations=0;"
        "live=no;signer=no;submission=0;paper=0;commit=no;push=no;deploy=no"
    )
    print("M299_FINAL=PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", default="")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        lineage_preflight()
        print(
            "M299_RUNNER_SELFTEST=PASS;automatic_collection=false;"
            "explicit_confirmation_required=true;db_mutation_path=false"
        )
        return

    collect(args.confirm)


if __name__ == "__main__":
    try:
        main()
    except Stop as exc:
        print("M299_FINAL=FAIL;reason=" + str(exc))
        raise SystemExit(2)
