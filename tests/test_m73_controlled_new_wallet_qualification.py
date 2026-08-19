from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.app.services.gen4_controlled_new_wallet_qualification_service import (
    DISPOSITION_OBSERVE,
    DISPOSITION_QUALIFIED,
    DISPOSITION_REJECT,
    M73_RUN_CONFIRMATION,
    build_m73_report,
    canonical_sha256,
    choose_seed_wallet,
    classify_deep_candidate,
    extract_m66_candidates,
    validate_m73_report,
    validate_runtime_limits,
)


FIXTURE = Path(__file__).parent / "fixtures" / "m73_controlled_new_wallet_qualification.json"


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))




def test_verifier_bootstraps_project_root_before_backend_import():
    verifier = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "verify_m73_controlled_new_wallet_qualification.py"
    )
    source = verifier.read_text(encoding="utf-8")
    root_marker = "ROOT = Path(__file__).resolve().parents[1]"
    path_marker = "sys.path.insert(0, str(ROOT))"
    import_marker = (
        "from backend.app.services.gen4_controlled_new_wallet_qualification_service import"
    )
    assert root_marker in source
    assert path_marker in source
    assert import_marker in source
    assert source.index(root_marker) < source.index(path_marker) < source.index(import_marker)

def test_limits_are_hard_capped():
    limits = validate_runtime_limits(
        helius_requests=999,
        helius_credits=999999,
        helius_retries=99,
        public_rpc_requests=99999,
        deep_candidates=99,
        signatures_per_candidate=9999,
    )
    assert limits == {
        "helius_requests": 90,
        "helius_credits": 9000,
        "helius_retries": 0,
        "public_rpc_requests": 5000,
        "deep_candidates": 8,
        "signatures_per_candidate": 500,
    }


def test_confirmation_is_explicit_credit_spend_contract():
    assert M73_RUN_CONFIRMATION == "EXECUTE_M73_DISCOVERY_TRANCHE_MAX_9000_HELIUS_CREDITS"


def test_extract_candidates_deduplicates_and_ranks():
    fixture = load_fixture()
    documents = [("m66.json", fixture["documents"])]
    rows = extract_m66_candidates(documents, excluded_wallets=set(fixture["excluded"]))
    assert len(rows) == 3
    assert [row["prescreen_score"] for row in rows] == [88.0, 72.0, 64.0]


def test_extract_candidates_excludes_old_wallets():
    fixture = load_fixture()
    old = fixture["excluded"][0]
    rows = extract_m66_candidates(
        [("m66.json", [{"wallet_address": old, "score": 100}, *fixture["documents"]])],
        excluded_wallets={old},
    )
    assert old not in {row["wallet_address"] for row in rows}


def test_choose_seed_prefers_observe_with_more_closed_trades():
    report = {
        "wallet_rotation": [
            {"wallet_address":"ATXuKMwQGfXKpbSaAWAj8k6t58kGAa8QB4Jts29TdW9","disposition":"OBSERVE_ONLY","closed_trade_count":0,"buy_events":22,"parsed_event_count":31,"transaction_count":233},
            {"wallet_address":"F2BnACAArM3Wiz3wKF3xDpNZeRVH8MSZCzFnsaCi6qQg","disposition":"OBSERVE_ONLY","closed_trade_count":2,"buy_events":22,"parsed_event_count":33,"transaction_count":101},
        ]
    }
    assert choose_seed_wallet(report) == "F2BnACAArM3Wiz3wKF3xDpNZeRVH8MSZCzFnsaCi6qQg"


def test_classification_cases_are_fail_closed():
    fixture = load_fixture()
    expected = []
    actual = []
    for case in fixture["classification_cases"]:
        deep = {
            "wallet_address": case["wallet_address"],
            "history_complete": case["history_complete"],
            "signature_count": case["transaction_count"],
            "transaction_count": case["transaction_count"],
            "parsed_event_count": case["parsed_event_count"],
            "backtest": {"metrics": case["metrics"]},
        }
        result = classify_deep_candidate(
            {"wallet_address": case["wallet_address"], "prescreen_score": 50},
            deep,
            {"economic_gate_passed": case["economic_gate_passed"], "metrics": case["metrics"]},
        )
        expected.append(case["expected"])
        actual.append(result["disposition"])
    assert actual == expected


def test_incomplete_history_can_never_qualify_even_if_economics_looks_good():
    wallet = "77777777777777777777777777777777"
    metrics = {"buy_signals":120,"sell_signals":120,"closed_trade_count":120,"open_positions":0}
    result = classify_deep_candidate(
        {"wallet_address": wallet},
        {"wallet_address":wallet,"history_complete":False,"transaction_count":500,"parsed_event_count":400,"backtest":{"metrics":metrics}},
        {"economic_gate_passed": True, "metrics": metrics},
    )
    assert result["disposition"] == DISPOSITION_OBSERVE
    assert result["short_canary_required"] is False


def test_qualified_candidate_still_does_not_authorize_canary_or_live():
    report = build_m73_report(
        m72_report_sha256="a"*64,
        m72_plan_sha256="b"*64,
        seed_wallet="F2BnACAArM3Wiz3wKF3xDpNZeRVH8MSZCzFnsaCi6qQg",
        m66_files=[],
        discovered_candidates=[],
        evaluated_candidates=[{"wallet_address":"77777777777777777777777777777777","disposition":DISPOSITION_QUALIFIED}],
        helius_accounting={"requests_reported":86,"credits_reported":8600},
        public_rpc_stats={"requests":100,"cache_hits":20},
        limits=validate_runtime_limits(),
        cache_payload_sha256="c"*64,
        evaluated_at=datetime(2026,8,15,tzinfo=timezone.utc),
    )
    validate_m73_report(report)
    assert report["summary"]["qualified_pending_short_canary"] == 1
    assert report["decision"]["short_canary_execution_authorized"] is False
    assert report["decision"]["micro_live_execution_authorized"] is False
    assert report["decision"]["signer_authorized"] is False


def test_report_hash_covers_payload():
    report = build_m73_report(
        m72_report_sha256="a"*64,m72_plan_sha256="b"*64,seed_wallet="F2BnACAArM3Wiz3wKF3xDpNZeRVH8MSZCzFnsaCi6qQg",
        m66_files=[],discovered_candidates=[],evaluated_candidates=[],helius_accounting={},public_rpc_stats={},limits=validate_runtime_limits(),cache_payload_sha256="c"*64,
        evaluated_at=datetime(2026,8,15,tzinfo=timezone.utc),
    )
    assert validate_m73_report(report)["report_payload_sha256"] == report["integrity"]["report_payload_sha256"]



def test_hotfix2_database_preflight_is_before_lock_in_runner_source():
    runner = Path(__file__).resolve().parents[1] / "scripts" / "run_m73_controlled_new_wallet_qualification.py"
    source = runner.read_text(encoding="utf-8")
    db_call = "database_public_url_source = _preflight_database_public_url()"
    lock_call = "started, lock_state = _prepare_execution_lock("
    m66_call = "m66_output = _invoke_m66_lane("
    assert db_call in source and lock_call in source and m66_call in source
    assert source.index(db_call) < source.index(lock_call) < source.index(m66_call)


def test_hotfix2_wrapper_uses_existing_m67_railway_postgres_pattern():
    wrapper = Path(__file__).resolve().parents[1] / "RUN_M73_CONTROLLED_NEW_WALLET_QUALIFICATION.ps1"
    source = wrapper.read_text(encoding="utf-8-sig")
    for token in (
        "Get-Command railway.cmd",
        '"run"',
        '"--service", "Postgres"',
        '"--environment", "production"',
        '"--no-local"',
        "$python",
    ):
        assert token in source
    assert "$env:DATABASE_URL" not in source


def test_hotfix2_recovery_token_is_explicit_and_not_automatic():
    runner = Path(__file__).resolve().parents[1] / "scripts" / "run_m73_controlled_new_wallet_qualification.py"
    source = runner.read_text(encoding="utf-8")
    assert "RECOVER_M73_PRENETWORK_DATABASE_PUBLIC_URL_FAILURE_HOTFIX2" in source
    assert "automatic_rearm\": False" in source
    assert "M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256" in source


def test_hotfix3_helius_resolution_is_before_lock_and_m66():
    runner = Path(__file__).resolve().parents[1] / "scripts" / "run_m73_controlled_new_wallet_qualification.py"
    source = runner.read_text(encoding="utf-8")
    db_call = "database_public_url_source = _preflight_database_public_url()"
    secret_call = "helius_api_key, helius_api_key_source, helius_key_evidence = _resolve_helius_api_key()"
    lock_call = "started, lock_state = _prepare_execution_lock("
    m66_call = "m66_output = _invoke_m66_lane("
    assert all(token in source for token in (db_call, secret_call, lock_call, m66_call))
    assert source.index(db_call) < source.index(secret_call) < source.index(lock_call) < source.index(m66_call)


def test_hotfix3_removes_parent_helius_before_railway_backend_probe(monkeypatch):
    import base64
    import scripts.run_m73_controlled_new_wallet_qualification as runner

    captured = {}
    backend_key = "backend-key-abcdefghijklmnopqrstuvwxyz"

    class Result:
        returncode = 0
        stdout = "M73_SECRET_CAPTURE_B64=" + base64.b64encode(backend_key.encode()).decode() + "\n"
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = list(command)
        captured["env"] = dict(kwargs["env"])
        return Result()

    monkeypatch.setenv("HELIUS_API_KEY", "parent-key-abcdefghijklmnopqrstuvwxyz")
    monkeypatch.setattr(runner, "_railway_executable", lambda: "railway.cmd")
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    value = runner._railway_backend_helius_key()

    assert value == backend_key
    assert "HELIUS_API_KEY" not in captured["env"]
    assert captured["command"][:7] == [
        "railway.cmd", "run", "--service", "smartmoney-ai",
        "--environment", "production", "--no-local",
    ]
    assert backend_key not in " ".join(captured["command"])


def test_hotfix3_railway_backend_key_has_priority(monkeypatch, tmp_path):
    import scripts.run_m73_controlled_new_wallet_qualification as runner

    railway = "railway-key-abcdefghijklmnopqrstuvwxyz"
    local = "local-dotenv-key-abcdefghijklmnopqrstuvwxyz"
    env = "parent-env-key-abcdefghijklmnopqrstuvwxyz"
    (tmp_path / ".env").write_text(f"HELIUS_API_KEY={local}\n", encoding="utf-8")
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "_railway_backend_helius_key", lambda: railway)
    monkeypatch.setenv("HELIUS_API_KEY", env)

    key, source, evidence = runner._resolve_helius_api_key()
    assert key == railway
    assert source == "RAILWAY_BACKEND_UNSEALED"
    assert evidence["railway_backend_exported"] == "YES_REDACTED"
    assert evidence["local_dotenv_present"] == "YES_REDACTED"
    assert evidence["railway_matches_local_dotenv"] == "NO"


def test_hotfix3_sealed_railway_falls_back_to_local_dotenv(monkeypatch, tmp_path):
    import scripts.run_m73_controlled_new_wallet_qualification as runner

    local = "local-dotenv-key-abcdefghijklmnopqrstuvwxyz"
    (tmp_path / ".env").write_text(f'HELIUS_API_KEY="{local}"\n', encoding="utf-8")
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "_railway_backend_helius_key", lambda: "")
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)

    key, source, evidence = runner._resolve_helius_api_key()
    assert key == local
    assert source == "LOCAL_DOTENV"
    assert evidence["railway_backend_exported"] == "NO_OR_SEALED"
    assert evidence["local_dotenv_present"] == "YES_REDACTED"
    assert evidence["railway_matches_local_dotenv"] == "NOT_COMPARABLE"


def test_hotfix3_inherited_env_is_last_resort(monkeypatch, tmp_path):
    import scripts.run_m73_controlled_new_wallet_qualification as runner

    inherited = "inherited-key-abcdefghijklmnopqrstuvwxyz"
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "_railway_backend_helius_key", lambda: "")
    monkeypatch.setenv("HELIUS_API_KEY", inherited)

    key, source, evidence = runner._resolve_helius_api_key()
    assert key == inherited
    assert source == "INHERITED_PROCESS_ENVIRONMENT"
    assert evidence["local_dotenv_present"] == "NO"


def test_hotfix3_missing_all_helius_sources_fails_closed_before_lock(monkeypatch, tmp_path):
    import pytest
    import scripts.run_m73_controlled_new_wallet_qualification as runner

    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(runner, "_railway_backend_helius_key", lambda: "")
    monkeypatch.delenv("HELIUS_API_KEY", raising=False)
    with pytest.raises(runner.M73ControlledQualificationError, match="HELIUS_API_KEY non risolvibile"):
        runner._resolve_helius_api_key()


def test_hotfix3_invalid_short_or_whitespace_keys_are_rejected():
    import scripts.run_m73_controlled_new_wallet_qualification as runner

    assert runner._valid_helius_api_key("") is False
    assert runner._valid_helius_api_key("short") is False
    assert runner._valid_helius_api_key("a" * 19) is False
    assert runner._valid_helius_api_key("a" * 20) is True
    assert runner._valid_helius_api_key("a" * 10 + " " + "b" * 20) is False
    assert runner._valid_helius_api_key("a" * 513) is False


def test_hotfix3_dotenv_parser_handles_quotes_comments_and_last_value(tmp_path):
    import scripts.run_m73_controlled_new_wallet_qualification as runner

    path = tmp_path / ".env"
    path.write_text(
        "# comment\nOTHER=1\nHELIUS_API_KEY='first-value-abcdefghijklmnopqrstuvwxyz'\n"
        'HELIUS_API_KEY="second-value-abcdefghijklmnopqrstuvwxyz"\n',
        encoding="utf-8",
    )
    assert runner._read_dotenv_value(path, "HELIUS_API_KEY") == "second-value-abcdefghijklmnopqrstuvwxyz"


def test_hotfix3_resolver_performs_no_helius_provider_call():
    runner = Path(__file__).resolve().parents[1] / "scripts" / "run_m73_controlled_new_wallet_qualification.py"
    source = runner.read_text(encoding="utf-8")
    start = source.index("def _resolve_helius_api_key")
    end = source.index("def _sanitize_sensitive_output", start)
    body = source[start:end]
    assert "get_helius_health" not in body
    assert "mainnet.helius" not in body
    assert "api.helius" not in body
    assert "httpx" not in body


def test_hotfix3_sensitive_output_redacts_exact_key_api_query_and_database_password():
    import scripts.run_m73_controlled_new_wallet_qualification as runner

    secret = "secret-key-abcdefghijklmnopqrstuvwxyz"
    raw = (
        f"HELIUS_API_KEY={secret}\n"
        f"https://x.test/path?api-key={secret}\n"
        "postgresql://user:password123@host.example/db\n"
    )
    safe = runner._sanitize_sensitive_output(raw, helius_api_key=secret)
    assert secret not in safe
    assert "password123" not in safe
    assert "<REDACTED" in safe


def test_hotfix3_m66_receives_explicit_key_and_stdout_is_sanitized(monkeypatch, tmp_path, capsys):
    import scripts.run_m73_controlled_new_wallet_qualification as runner

    secret = "secret-key-abcdefghijklmnopqrstuvwxyz"
    captured = {}

    class Result:
        returncode = 0
        stdout = (
            "M73_M66_PARAMETER_BINDING=PASS\n"
            "M66_CONTROLLED_HELIUS_DISCOVERY=PASS\n"
            f"HELIUS_API_KEY={secret}\n"
        )
        stderr = ""

    def fake_run(command, **kwargs):
        captured["env"] = dict(kwargs["env"])
        return Result()

    monkeypatch.setattr(runner, "_powershell_executable", lambda: "powershell.exe")
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    result = runner._invoke_m66_lane(
        tmp_path / "RUN_M66_CONTROLLED_HELIUS_DISCOVERY.ps1",
        output_dir=tmp_path,
        seed_wallet="F2BnACAArM3Wiz3wKF3xDpNZeRVH8MSZCzFnsaCi6qQg",
        helius_api_key=secret,
    )
    visible = capsys.readouterr().out
    assert captured["env"]["HELIUS_API_KEY"] == secret
    assert secret not in result
    assert secret not in visible
    assert "<REDACTED>" in result or "<REDACTED_HELIUS_API_KEY>" in result


def test_hotfix3_m66_rejects_invalid_key_before_subprocess(monkeypatch, tmp_path):
    import pytest
    import scripts.run_m73_controlled_new_wallet_qualification as runner

    monkeypatch.setattr(runner, "_powershell_executable", lambda: "powershell.exe")
    called = {"value": False}

    def fake_run(*args, **kwargs):
        called["value"] = True
        raise AssertionError("subprocess must not run")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    with pytest.raises(runner.M73ControlledQualificationError, match="risolta non valida"):
        runner._invoke_m66_lane(
            tmp_path / "RUN_M66_CONTROLLED_HELIUS_DISCOVERY.ps1",
            output_dir=tmp_path,
            seed_wallet="seed",
            helius_api_key="bad",
        )
    assert called["value"] is False


def test_hotfix3_old_generic_railway_runtime_probe_is_removed():
    runner = Path(__file__).resolve().parents[1] / "scripts" / "run_m73_controlled_new_wallet_qualification.py"
    source = runner.read_text(encoding="utf-8")
    assert "def _preflight_m66_runtime_environment" not in source
    assert "RAILWAY_SMARTMONEY_AI_MERGED_WITH_PARENT_ENVIRONMENT" not in source


def test_expanded_m66_hash_lock_and_9000_cap_are_exact():
    import scripts.run_m73_controlled_new_wallet_qualification as runner

    assert runner.EXPECTED_M66_WRAPPER_SHA256 == "665e267616bf50ef45864490d26f0cf4d5c8a37db1490000bba63a78f9a0ea81"
    assert runner.EXPECTED_M66_SERVICE_SHA256 == "f4312154f95a9256c5a02e62dd4a100414d28c9ed3812159c9b3a75f23e5581a"
    assert runner.EXPECTED_M66_RUNNER_SHA256 == "21da3da6d63c49d4c1443091552f44fbbc302579f19db3a2973c639673096ec4"
    assert runner._accounting("HELIUS_REQUESTS=86\nHELIUS_CREDITS=8600\n")["credit_cap"] == 9000





def _hotfix4_runner():
    import scripts.run_m73_controlled_new_wallet_qualification as runner_module
    return runner_module


def test_hotfix4_runtime_env_explicitly_enforces_m63_guard_only_for_m66(monkeypatch):
    runner = _hotfix4_runner()
    monkeypatch.setenv("ENVIRONMENT", "development")
    env = runner._m66_runtime_env("h" * 36)
    assert env["HELIUS_API_KEY"] == "h" * 36
    assert env["HELIUS_CREDIT_GUARD_ENABLED"] == "true"
    assert env["HELIUS_CREDIT_GUARD_ENFORCE_IN_NON_PRODUCTION"] == "true"
    assert env["HELIUS_AUTOMATIC_ENHANCED_API_ENABLED"] == "false"
    assert env.get("ENVIRONMENT") == "development"


def test_hotfix4_real_m63_guard_semantics_enforce_in_development(monkeypatch):
    from backend.app.core.config import settings
    from backend.app.services import helius_credit_guard_service as guard

    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "HELIUS_CREDIT_GUARD_ENABLED", True)
    monkeypatch.setattr(settings, "HELIUS_CREDIT_GUARD_ENFORCE_IN_NON_PRODUCTION", False)
    assert guard._guard_enforced() is False
    monkeypatch.setattr(settings, "HELIUS_CREDIT_GUARD_ENFORCE_IN_NON_PRODUCTION", True)
    assert guard._guard_enforced() is True


def test_hotfix4_credit_guard_preflight_uses_zero_network_and_exact_env(monkeypatch):
    runner = _hotfix4_runner()
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["env"] = dict(kwargs["env"])
        return type("Completed", (), {
            "returncode": 0,
            "stdout": "M73_M63_LOCAL_CREDIT_GUARD=ENFORCED\n",
            "stderr": "",
        })()

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    result = runner._preflight_m63_credit_guard("k" * 36)
    assert result == {
        "guard_enabled": "YES",
        "enforce_in_non_production": "YES",
        "automatic_enhanced_api": "DISABLED",
        "network_requests": "0",
    }
    assert captured["env"]["HELIUS_CREDIT_GUARD_ENABLED"] == "true"
    assert captured["env"]["HELIUS_CREDIT_GUARD_ENFORCE_IN_NON_PRODUCTION"] == "true"
    assert captured["env"]["HELIUS_AUTOMATIC_ENHANCED_API_ENABLED"] == "false"
    joined = " ".join(captured["command"])
    assert "httpx" not in joined.lower()
    assert "https://" not in joined.lower()
    assert "api.helius" not in joined.lower()
    assert "get_wallet_history" not in joined.lower()


def _hotfix3_guard_failure_lock(runner, now):
    return {
        "scope": runner._M73_LOCK_SCOPE,
        "state": "RECOVERING_PRENETWORK_DATABASE_PUBLIC_URL_FAILURE_HOTFIX2",
        "started_at_utc": (now - __import__("datetime").timedelta(minutes=10)).isoformat(),
        "m72_plan_file_sha256": runner.M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256,
        "helius_maximum_requests": 6,
        "helius_credit_cap": 600,
        "helius_retries": 0,
        "automatic_rearm": False,
        "recovery_used": True,
        "recovery_started_at_utc": (now - __import__("datetime").timedelta(minutes=5)).isoformat(),
        "recovery_reason": "DATABASE_PUBLIC_URL_MISSING_BEFORE_M66_NETWORK_PREFLIGHT",
        "recovery_contract": "EXACT_PLAN_EXACT_STARTED_LOCK_NO_NEW_M66_M73_OUTPUTS",
    }


def test_hotfix4_exact_guard_failure_lock_can_recover_once(tmp_path):
    runner = _hotfix4_runner()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    lock = tmp_path / "smartmoney-m73-controlled-execution-lock-test.json"
    runner.write_json_atomic(lock, _hotfix3_guard_failure_lock(runner, now))
    started, payload = runner._prepare_execution_lock(
        lock,
        output_dir=tmp_path,
        m72_plan_file_sha256=runner.M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256,
        recovery_confirmation=runner.M73_HOTFIX4_RECOVERY_CONFIRMATION,
        started=now,
    )
    assert started == now
    assert payload["state"] == "RECOVERING_PRENETWORK_CREDIT_GUARD_NOT_ENFORCED_HOTFIX3"
    assert payload["hotfix4_recovery_used"] is True
    assert payload["hotfix4_recovery_reason"] == "M63_CREDIT_GUARD_NOT_ENFORCED_BEFORE_FIRST_HELIUS_REQUEST"


def test_hotfix4_old_hotfix2_started_lock_is_not_generic_rearmed(tmp_path):
    runner = _hotfix4_runner()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    lock = tmp_path / "smartmoney-m73-controlled-execution-lock-test.json"
    runner.write_json_atomic(lock, {
        "scope": runner._M73_LOCK_SCOPE,
        "state": "STARTED",
        "started_at_utc": now.isoformat(),
        "m72_plan_file_sha256": runner.M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256,
        "helius_maximum_requests": 6,
        "helius_credit_cap": 600,
        "helius_retries": 0,
        "automatic_rearm": False,
    })
    with pytest.raises(runner.M73ControlledQualificationError, match="Hotfix3 noto"):
        runner._prepare_execution_lock(
            lock,
            output_dir=tmp_path,
            m72_plan_file_sha256=runner.M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256,
            recovery_confirmation=runner.M73_HOTFIX4_RECOVERY_CONFIRMATION,
            started=now,
        )


def test_hotfix4_post_hotfix3_artifact_blocks_recovery(tmp_path):
    runner = _hotfix4_runner()
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    lock = tmp_path / "smartmoney-m73-controlled-execution-lock-test.json"
    payload = _hotfix3_guard_failure_lock(runner, now)
    runner.write_json_atomic(lock, payload)
    artifact = tmp_path / "smartmoney-m66-controlled-output.json"
    artifact.write_text("{}", encoding="utf-8")
    # Make artifact unambiguously newer than the Hotfix3 recovery start.
    import os as _os
    ts = (now + timedelta(seconds=1)).timestamp()
    _os.utime(artifact, (ts, ts))
    with pytest.raises(runner.M73ControlledQualificationError, match="output M66/M73"):
        runner._prepare_execution_lock(
            lock,
            output_dir=tmp_path,
            m72_plan_file_sha256=runner.M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256,
            recovery_confirmation=runner.M73_HOTFIX4_RECOVERY_CONFIRMATION,
            started=now,
        )


def test_hotfix4_guard_preflight_is_before_lock_in_main_source():
    runner = _hotfix4_runner()
    source = Path(runner.__file__).read_text(encoding="utf-8")
    main = source[source.index("def main()") :]
    assert main.index("m63_guard_preflight = _preflight_m63_credit_guard") < main.index("_prepare_execution_lock(")
    assert main.index("_prepare_execution_lock(") < main.index("m66_output = _invoke_m66_lane(")

HOTFIX5_POST429_LOCK_FIXTURE = (
    Path(__file__).parent / "fixtures" / "m73_hotfix5_known_post429_lock.json"
)


def _copy_hotfix5_known_lock(target: Path) -> None:
    target.write_bytes(HOTFIX5_POST429_LOCK_FIXTURE.read_bytes())


def test_hotfix5_known_post429_lock_fixture_has_exact_observed_sha():
    runner = _hotfix4_runner()
    assert runner._sha256(HOTFIX5_POST429_LOCK_FIXTURE) == (
        runner.M73_HOTFIX5_KNOWN_FAILED_LOCK_SHA256
    )
    assert runner.M73_HOTFIX5_KNOWN_PRIOR_PROVIDER_ATTEMPTS == 1
    assert runner.M73_HOTFIX5_KNOWN_PRIOR_HTTP_STATUS == 429


def test_hotfix5_exact_post429_lock_recovers_once_and_archives_original(tmp_path):
    runner = _hotfix4_runner()
    lock = tmp_path / "smartmoney-m73-controlled-execution-lock-test.json"
    _copy_hotfix5_known_lock(lock)
    original_sha = runner._sha256(lock)
    now = datetime.now(timezone.utc)

    started, payload = runner._prepare_execution_lock(
        lock,
        output_dir=tmp_path,
        m72_plan_file_sha256=runner.M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256,
        recovery_confirmation=runner.M73_HOTFIX5_POST429_RECOVERY_CONFIRMATION,
        started=now,
    )

    assert started == now
    assert payload["state"] == "RECOVERING_POST_PROVIDER_HTTP_429_HOTFIX4"
    assert payload["hotfix5_post429_recovery_used"] is True
    assert payload["hotfix5_post429_previous_provider_attempts"] == 1
    assert payload["hotfix5_post429_previous_http_status"] == 429
    assert payload["hotfix5_post429_source_lock_sha256"] == original_sha
    archive = Path(payload["hotfix5_post429_archive_file"])
    assert archive.is_file()
    assert runner._sha256(archive) == original_sha
    assert runner._sha256(lock) != original_sha

    with pytest.raises(
        runner.M73ControlledQualificationError,
        match="SHA del lock M73 non coincide",
    ):
        runner._prepare_execution_lock(
            lock,
            output_dir=tmp_path,
            m72_plan_file_sha256=runner.M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256,
            recovery_confirmation=runner.M73_HOTFIX5_POST429_RECOVERY_CONFIRMATION,
            started=now,
        )


def test_hotfix5_wrong_lock_sha_is_fail_closed(tmp_path):
    runner = _hotfix4_runner()
    lock = tmp_path / "smartmoney-m73-controlled-execution-lock-test.json"
    _copy_hotfix5_known_lock(lock)
    lock.write_bytes(lock.read_bytes() + b" ")

    with pytest.raises(
        runner.M73ControlledQualificationError,
        match="SHA del lock M73 non coincide",
    ):
        runner._prepare_execution_lock(
            lock,
            output_dir=tmp_path,
            m72_plan_file_sha256=runner.M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256,
            recovery_confirmation=runner.M73_HOTFIX5_POST429_RECOVERY_CONFIRMATION,
            started=datetime.now(timezone.utc),
        )


def test_hotfix5_post429_recovery_requires_explicit_new_token(tmp_path):
    runner = _hotfix4_runner()
    lock = tmp_path / "smartmoney-m73-controlled-execution-lock-test.json"
    _copy_hotfix5_known_lock(lock)

    with pytest.raises(
        runner.M73ControlledQualificationError,
        match="Nessun re-arm automatico",
    ):
        runner._prepare_execution_lock(
            lock,
            output_dir=tmp_path,
            m72_plan_file_sha256=runner.M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256,
            recovery_confirmation="",
            started=datetime.now(timezone.utc),
        )


def test_hotfix5_post429_artifact_blocks_recovery(tmp_path):
    runner = _hotfix4_runner()
    lock = tmp_path / "smartmoney-m73-controlled-execution-lock-test.json"
    _copy_hotfix5_known_lock(lock)
    artifact = tmp_path / "smartmoney-m66-controlled-helius-discovery-after429.json"
    artifact.write_text("{}", encoding="utf-8")

    with pytest.raises(
        runner.M73ControlledQualificationError,
        match="esistono output M66/M73 successivi",
    ):
        runner._prepare_execution_lock(
            lock,
            output_dir=tmp_path,
            m72_plan_file_sha256=runner.M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256,
            recovery_confirmation=runner.M73_HOTFIX5_POST429_RECOVERY_CONFIRMATION,
            started=datetime.now(timezone.utc),
        )


def test_hotfix5_wrapper_uses_reachable_recovery_markers():
    wrapper = (
        Path(__file__).resolve().parents[1]
        / "RUN_M73_CONTROLLED_NEW_WALLET_QUALIFICATION.ps1"
    ).read_text(encoding="utf-8-sig")
    assert "M73_LOCK_RECOVERY_MODE=" in wrapper
    assert "M73_HOTFIX5_POST429_LOCK_RECOVERY=" in wrapper
    assert "M73_HELIUS_MAXIMUM_REQUESTS=90" in wrapper
    assert "M73_HELIUS_CREDIT_CAP=9000" in wrapper
    assert "M73_HOTFIX2_LOCK_RECOVERY=" not in wrapper
