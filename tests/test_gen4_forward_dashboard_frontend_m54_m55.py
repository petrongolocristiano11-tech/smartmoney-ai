from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_gen4_forward_route_and_navigation_are_registered() -> None:
    main = _read("frontend/src/main.jsx")
    navbar = _read("frontend/src/components/Navbar.jsx")

    assert 'import("./pages/Gen4Forward.jsx")' in main
    assert 'path="/gen4-forward"' in main
    assert "element={<Gen4Forward />}" in main
    assert 'label: "Gen 4 Forward"' in navbar
    assert 'path: "/gen4-forward"' in navbar


def test_gen4_forward_frontend_uses_only_m52_m53_shadow_endpoints() -> None:
    api = _read("frontend/src/services/gen4ForwardApi.js")

    assert '"X-Automation-Key"' in api
    assert '"/integrity/parser-gen4-forward"' in api
    assert "`${GEN4_FORWARD_BASE}/status`" in api
    assert "`${GEN4_FORWARD_BASE}/campaigns/${encodeURIComponent(campaignId)}`" in api
    assert "`${GEN4_FORWARD_BASE}/cycle`" in api
    assert 'confirmation: "RUN_GEN4_STRICT_FORWARD_CYCLE"' in api

    forbidden = (
        "/paper-trading",
        "/live-trading",
        "X-Live-Trading-Key",
        "private_key",
        "secret_key",
        "Jupiter",
        "Helius",
    )
    for marker in forbidden:
        assert marker not in api


def test_gen4_forward_page_has_access_gate_progress_lanes_and_manual_cycle() -> None:
    page = _read("frontend/src/pages/Gen4Forward.jsx")

    assert "AUTOMATION_API_KEY" in page
    assert "sessionStorage" in page
    assert "Esegui ciclo shadow" in page
    assert "STRICT_GEN4_FORWARD" in page
    assert "SIGNAL_ONLY_FORWARD" in page
    assert "SIMPLE_COPY_FORWARD_BASELINE" in page
    assert "Gen4ForwardProgress" in page
    assert "Gen4ForwardEquityChart" in page
    assert "Gen4FrozenWallets" in page
    assert "Gen4CycleTable" in page
    assert "Gen4DecisionTable" in page
    assert "decisionLimit: 1000" in page
    assert "setInterval" in page
    assert "GEN4_FORWARD_AUTO_REFRESH_MS" in page
    assert 'status?.enabled !== true' in page
    assert 'Runtime shadow OFF' in page
    assert 'Runtime shadow: {status?.enabled ? "ON" : "OFF"}' in page


def test_gen4_forward_auto_refresh_is_not_aggressive() -> None:
    formatters = _read(
        "frontend/src/components/gen4Forward/gen4ForwardFormatters.js"
    )
    assert "GEN4_FORWARD_AUTO_REFRESH_MS = 15_000" in formatters


def test_gen4_forward_equity_curve_uses_closed_accepted_decisions_only() -> None:
    formatters = _read(
        "frontend/src/components/gen4Forward/gen4ForwardFormatters.js"
    )
    assert 'row.status === "CLOSED"' in formatters
    assert "row.portfolio_accepted" in formatters
    assert "Number.isFinite(Number(row.pnl_sol))" in formatters
    assert "totals.STRICT_GEN4_FORWARD" in formatters
    assert "totals.SIGNAL_ONLY_FORWARD" in formatters
    assert "totals.SIMPLE_COPY_FORWARD_BASELINE" in formatters


def test_backend_m52_m53_endpoints_remain_key_protected() -> None:
    main = _read("backend/app/main.py")
    expected_routes = (
        '@app.get("/integrity/parser-gen4-forward/status"',
        '@app.post("/integrity/parser-gen4-forward/cycle"',
        '@app.get("/integrity/parser-gen4-forward/campaigns/{campaign_id}"',
    )
    for route in expected_routes:
        assert route in main

    gen4_block = main.split(
        "# BEGIN M52-M53 GEN4 STRICT FORWARD SHADOW CAMPAIGN",
        maxsplit=1,
    )[1].split(
        "# END M52-M53 GEN4 STRICT FORWARD SHADOW CAMPAIGN",
        maxsplit=1,
    )[0]
    assert gen4_block.count("Depends(require_automation_key)") >= 6


def test_gen4_forward_page_never_starts_scheduler_paper_or_live() -> None:
    combined = "\n".join(
        [
            _read("frontend/src/pages/Gen4Forward.jsx"),
            _read("frontend/src/services/gen4ForwardApi.js"),
        ]
    )

    forbidden_calls = (
        "startScheduler",
        "scheduler/start",
        "paper/order",
        "paper-trading/order",
        "live/arm",
        "live-trading/execute",
        "transactions/send",
        "signTransaction",
    )
    for marker in forbidden_calls:
        assert marker not in combined


def test_dashboard_verifier_bootstraps_project_root_from_external_cwd(tmp_path) -> None:
    import os
    import subprocess
    import sys

    verifier = ROOT / "scripts/verify_gen4_forward_dashboard_m54_m55.py"
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [sys.executable, str(verifier), "--structure-only"],
        cwd=tmp_path,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "GEN4_FORWARD_DASHBOARD_STRUCTURE=OK" in result.stdout
    assert "DATABASE_CHECK=SKIPPED" in result.stdout
