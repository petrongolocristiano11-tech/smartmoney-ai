from pathlib import Path


def test_m61_frontend_exposes_isolated_campaign_selector():
    panel = Path(
        "frontend/src/components/gen4Forward/Gen4CopyabilityPanel.jsx"
    ).read_text(encoding="utf-8")
    api = Path("frontend/src/services/gen4ForwardApi.js").read_text(encoding="utf-8")
    page = Path("frontend/src/pages/Gen4Forward.jsx").read_text(encoding="utf-8")

    assert "active_campaigns" in panel
    assert "PRIMARY_FORWARD" in panel
    assert "QUALIFIED_CANDIDATE" not in panel  # label is user-facing, not raw enum
    assert "una campagna contamini l’altra" in panel
    assert "Campagne" in panel
    assert "start-qualified-candidate" in api
    assert "START_GEN4_QUALIFIED_CANDIDATE_COPYABILITY" in api
    assert "campaign_id" in api
    assert "Campagne copyability" in page


def test_m61_frontend_keeps_all_execution_paths_absent():
    files = [
        Path("frontend/src/components/gen4Forward/Gen4CopyabilityPanel.jsx"),
        Path("frontend/src/services/gen4ForwardApi.js"),
        Path("frontend/src/pages/Gen4Forward.jsx"),
    ]
    joined = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert "execute_order" not in joined
    assert "private_key" not in joined.lower()
    assert "signed_transactions:" not in joined.lower()
    assert "signed_transaction =" not in joined.lower()
    assert "automatic_live_activation: true" not in joined.lower()
