from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_contains_candidate_funnel_controls_and_queue():
    api = (
        ROOT / "frontend/src/services/api.js"
    ).read_text(encoding="utf-8")
    page = (
        ROOT / "frontend/src/pages/Discovery.jsx"
    ).read_text(encoding="utf-8")
    assert "refreshCandidateFunnel" in api
    assert "/discovered-wallets/candidate-funnel/refresh" in api
    assert "Discovery Candidate Funnel + Budgeted History Queue" in page
    assert "Candidate Funnel Result" in page
    assert "DISCOVERY_FUNNEL_OPTIONS" in page
    assert "history_queue" in page
    assert "Calcola candidate funnel" in page
    assert "parameters?.resumed" in page
    assert "Cursore iniziale" in page
    assert '"RIPRESA" : "NUOVA"' in page
    assert "ripreso dal cursore salvato" in page


def test_discovery_frontend_has_no_known_mojibake():
    page = (
        ROOT / "frontend/src/pages/Discovery.jsx"
    ).read_text(encoding="utf-8")
    for broken in ("Ã", "Â", "â†", "â€™"):
        assert broken not in page
    assert "Il backfill storico è manuale" in page
    assert "SOL→token→SOL" in page
    assert "Ricalcola qualità DB" in page
    assert "Ricalcola attività DB" in page



def test_candidate_wallet_selection_is_explicit_and_stable():
    page = (
        ROOT / "frontend/src/pages/Discovery.jsx"
    ).read_text(encoding="utf-8")

    assert (
        'useCallback(async (preferredWallet = "")'
        in page
    )
    assert (
        'typeof preferredWallet === "string"'
        in page
    )
    assert (
        '?.wallet_address ?? rows[0]?.wallet_address ?? ""'
        not in page
    )
    assert (
        "Seleziona esplicitamente un wallet"
        in page
    )
    assert "selectedCandidate" in page
    assert "Wallet selezionato:" in page
    assert (
        page.count(
            "await loadDiscoveredWallets(wallet);"
        )
        >= 2
    )


def test_candidate_funnel_queue_selection_is_request_free():
    page = (
        ROOT / "frontend/src/pages/Discovery.jsx"
    ).read_text(encoding="utf-8")

    start = page.index(
        "function handleSelectFunnelWallet"
    )
    end = page.index(
        "async function handleRunDiscovery",
        start,
    )
    handler = page[start:end]

    assert "handleCandidateWalletSelection" in handler
    assert "setHistoryRequestBudget" in handler
    assert (
        "runExtendedCandidateHistoryBackfill"
        not in handler
    )
    assert (
        "runCandidatePromotionBacktest"
        not in handler
    )
    assert "refreshCandidateFunnel" not in handler

    assert (
        "handleSelectFunnelWallet(row)"
        in page
    )
    assert 'id="candidate-analysis"' in page
    assert '"Selezionato"' in page
