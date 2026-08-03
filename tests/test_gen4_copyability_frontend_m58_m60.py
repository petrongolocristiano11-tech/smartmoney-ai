from pathlib import Path


def test_copyability_dashboard_is_wired_to_gen4_forward_page():
    page = Path("frontend/src/pages/Gen4Forward.jsx").read_text(encoding="utf-8")
    panel = Path("frontend/src/components/gen4Forward/Gen4CopyabilityPanel.jsx").read_text(
        encoding="utf-8"
    )
    api = Path("frontend/src/services/gen4ForwardApi.js").read_text(encoding="utf-8")

    assert "Gen4CopyabilityPanel" in page
    assert "getGen4CopyabilityStatus" in page
    assert "Real-time" in page
    assert "Webhook" in page
    assert "polling" in page.lower() and "recovery" in page.lower()
    assert "nessun paper / LIVE" in page

    assert "Real-Time Copyability" in panel
    assert "closed_copyable_trades" in panel
    assert "webhook_coverage_percent" in panel
    assert "entry_price_deterioration" in panel
    assert "RECOVERY_ONLY" in panel
    assert "attivazione automatica LIVE" in panel

    assert '"/integrity/parser-gen4-copyability"' in api
    assert "getGen4CopyabilityStatus" in api
    assert "processGen4CopyabilityQueue" in api


def test_frontend_does_not_expose_webhook_secret_or_live_activation():
    files = [
        Path("frontend/src/pages/Gen4Forward.jsx"),
        Path("frontend/src/components/gen4Forward/Gen4CopyabilityPanel.jsx"),
        Path("frontend/src/services/gen4ForwardApi.js"),
    ]
    joined = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert "CANONICAL_PARSER_GEN4_COPYABILITY_WEBHOOK_SECRET" not in joined
    assert "execute_order" not in joined
    assert "signedTransaction" not in joined
    assert "automatic_live_activation: true" not in joined
