from pathlib import Path


def test_expanded_discovery_contract_is_bounded_and_manual_only():
    service = Path("backend/app/services/gen4_controlled_helius_discovery_service.py").read_text(encoding="utf-8")
    wrapper = Path("RUN_M66_CONTROLLED_HELIUS_DISCOVERY.ps1").read_text(encoding="utf-8")
    runner = Path("scripts/run_m73_controlled_new_wallet_qualification.py").read_text(encoding="utf-8")
    assert "M66_MAX_ENHANCED_REQUESTS = 90" in service
    assert "M66_MAX_ENHANCED_CREDITS = 9_000" in service
    assert "M66_DEFAULT_PLANNED_REQUESTS = 86" in service
    assert "M66_DEFAULT_PLANNED_CREDITS = 8_600" in service
    assert "M66_MIN_PROVIDER_INTERVAL_SECONDS = 0.15" in service
    assert "time.sleep(remaining)" in service
    assert "SPEND_MAX_9000_HELIUS_CREDITS_FOR_M66_DISCOVERY_TRANCHE" in wrapper
    assert "HELIUS_RETRIES=0" in wrapper
    assert '"HELIUS_AUTOMATIC_ENHANCED_API_ENABLED": "false"' in runner
    assert "expanded_discovery_tranche_maximum_requests" in runner
    assert "expanded_discovery_tranche_credit_cap" in runner


def test_expanded_discovery_does_not_authorize_live():
    m66 = Path("RUN_M66_CONTROLLED_HELIUS_DISCOVERY.ps1").read_text(encoding="utf-8")
    m73 = Path("RUN_M73_CONTROLLED_NEW_WALLET_QUALIFICATION.ps1").read_text(encoding="utf-8")
    for token in ("MICRO_LIVE_EXECUTION_AUTHORIZED=NO", "SIGNER_AUTHORIZED=NO"):
        assert token in m66
        assert token in m73


def test_runtime_launcher_is_one_shot_and_no_auto_retry():
    source = Path("scripts/run_m66_m73_expanded_discovery_tranche.py").read_text(encoding="utf-8")
    assert "EXECUTE_M73_DISCOVERY_TRANCHE_MAX_9000_HELIUS_CREDITS" in source
    assert "RECOVER_M73_EXPANDED_AFTER_HOTFIX5_INTERRUPTED_EXACT_LOCK" in source
    assert '"-PublicRpcRequestCap","4000"' in source
    assert '"-MaximumCandidates","6"' in source
    assert 'print("AUTO_RETRY=NO")' in source
    assert "LIVE_AUTHORIZED=NO" in source
    assert "SIGNER_AUTHORIZED=NO" in source


def test_current_hotfix5_interrupted_lock_recovery_is_exact_and_one_shot(tmp_path):
    import shutil
    import pytest
    from scripts import run_m73_controlled_new_wallet_qualification as runner

    fixture = Path("tests/fixtures/m73_hotfix5_interrupted_current_lock.json")
    lock = tmp_path / "smartmoney-m73-controlled-execution-lock-test.json"
    shutil.copy2(fixture, lock)
    assert runner._sha256(lock) == runner.M73_EXPANDED_AFTER_HOTFIX5_KNOWN_LOCK_SHA256
    started = runner._parse_aware_iso("2026-08-16T14:30:00+00:00")
    returned_started, payload = runner._prepare_execution_lock(
        lock,
        output_dir=tmp_path,
        m72_plan_file_sha256=runner.M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256,
        recovery_confirmation=runner.M73_EXPANDED_AFTER_HOTFIX5_RECOVERY_CONFIRMATION,
        started=started,
    )
    assert returned_started == started
    assert payload["expanded_after_hotfix5_recovery_used"] is True
    assert payload["state"] == "RECOVERING_EXPANDED_DISCOVERY_AFTER_HOTFIX5_INTERRUPTED_RUN"
    assert payload["helius_maximum_requests"] == 90
    assert payload["helius_credit_cap"] == 9000
    assert payload["helius_retries"] == 0
    archive = Path(payload["expanded_after_hotfix5_archive_file"])
    assert runner._sha256(archive) == runner.M73_EXPANDED_AFTER_HOTFIX5_KNOWN_LOCK_SHA256
    with pytest.raises(runner.M73ControlledQualificationError):
        runner._prepare_execution_lock(
            lock,
            output_dir=tmp_path,
            m72_plan_file_sha256=runner.M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256,
            recovery_confirmation=runner.M73_EXPANDED_AFTER_HOTFIX5_RECOVERY_CONFIRMATION,
            started=started,
        )


def test_current_recovery_allows_m66_cache_but_blocks_completed_m73_report(tmp_path):
    import os
    import shutil
    import pytest
    from datetime import datetime, timezone
    from scripts import run_m73_controlled_new_wallet_qualification as runner

    fixture = Path("tests/fixtures/m73_hotfix5_interrupted_current_lock.json")
    lock = tmp_path / "smartmoney-m73-controlled-execution-lock-test.json"
    shutil.copy2(fixture, lock)
    after = datetime(2026, 8, 16, 14, 19, tzinfo=timezone.utc).timestamp()
    cache = tmp_path / "smartmoney-m66-helius-request-cache-test.json"
    cache.write_text("{}", encoding="utf-8")
    os.utime(cache, (after, after))
    started = datetime(2026, 8, 16, 14, 30, tzinfo=timezone.utc)
    _, payload = runner._prepare_execution_lock(
        lock,
        output_dir=tmp_path,
        m72_plan_file_sha256=runner.M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256,
        recovery_confirmation=runner.M73_EXPANDED_AFTER_HOTFIX5_RECOVERY_CONFIRMATION,
        started=started,
    )
    assert cache.name in payload["expanded_after_hotfix5_existing_m66_artifacts"]

    lock.unlink()
    shutil.copy2(fixture, lock)
    report = tmp_path / "smartmoney-m73-controlled-new-wallet-qualification-test.json"
    report.write_text("{}", encoding="utf-8")
    os.utime(report, (after, after))
    with pytest.raises(runner.M73ControlledQualificationError, match="esiste già un report M73"):
        runner._prepare_execution_lock(
            lock,
            output_dir=tmp_path,
            m72_plan_file_sha256=runner.M73_HOTFIX2_KNOWN_FAILED_PLAN_SHA256,
            recovery_confirmation=runner.M73_EXPANDED_AFTER_HOTFIX5_RECOVERY_CONFIRMATION,
            started=started,
        )
