from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_feed_panel_and_api_are_present():
    panel = (ROOT / "frontend/src/components/gen4Forward/Gen4ForwardFeedPanel.jsx").read_text(encoding="utf-8")
    page = (ROOT / "frontend/src/pages/Gen4Forward.jsx").read_text(encoding="utf-8")
    api = (ROOT / "frontend/src/services/gen4ForwardApi.js").read_text(encoding="utf-8")
    assert "Helius → database → ciclo Gen 4" in panel
    assert "daily_helius_requests" in panel
    assert "worker_running" in panel
    assert "Gen4ForwardFeedPanel" in page
    assert "Acquisisci ora" in page
    assert "runGen4ForwardFeedPoll" in page
    assert "/feed/status" in api
    assert "/feed/poll" in api
    assert "RUN_GEN4_FORWARD_FEED_POLL" in api


def test_feed_safety_copy_is_explicit():
    panel = (ROOT / "frontend/src/components/gen4Forward/Gen4ForwardFeedPanel.jsx").read_text(encoding="utf-8")
    page = (ROOT / "frontend/src/pages/Gen4Forward.jsx").read_text(encoding="utf-8")
    assert "point-in-time" in panel
    assert "lease" in panel.lower()
    assert "nessun paper / LIVE" in page


def test_frontend_preflight_uses_semantic_dry_run_not_title_string():
    patcher = (
        ROOT / "scripts/apply_gen4_forward_feed_frontend_m56_m57_patch.py"
    ).read_text(encoding="utf-8")
    assert "TemporaryDirectory" in patcher
    assert "patch_api(api_copy)" in patcher
    assert "patch_page(page_copy)" in patcher
    assert '"Gen4 Forward" not in page' not in patcher
