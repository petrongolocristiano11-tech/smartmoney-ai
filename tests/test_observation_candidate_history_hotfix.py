from pathlib import Path


ROW_ALLOWED_EXPRESSION = (
    '["COPIABILE", "OSSERVAZIONE"].includes('
    "wallet.quality_classification)"
)

SELECTED_ALLOWED_EXPRESSION = (
    '["COPIABILE", "OSSERVAZIONE"].includes('
    "discoveredWallets.find("
    "(wallet) => wallet.wallet_address === candidateWallet"
    ")?.quality_classification)"
)


def read_discovery_source() -> str:
    return Path(
        "frontend/src/pages/Discovery.jsx"
    ).read_text(encoding="utf-8")


def test_backend_allows_observation_candidates():
    source = Path(
        "backend/app/services/candidate_history_service.py"
    ).read_text(encoding="utf-8")

    assert (
        "allowed_history_quality_classifications"
        in source
    )
    assert '"COPIABILE"' in source
    assert '"OSSERVAZIONE"' in source
    assert (
        "not in allowed_history_quality_classifications"
        in source
    )


def test_frontend_selector_lists_all_discovered_wallets():
    source = read_discovery_source()

    label_index = source.find(
        "Wallet scoperto da analizzare"
    )

    assert label_index >= 0

    select_start = source.find(
        "<select",
        label_index,
    )
    select_end = source.find(
        "</select>",
        select_start,
    )

    assert select_start >= 0
    assert select_end >= 0

    selector = source[
        select_start:
        select_end + len("</select>")
    ]

    assert "discoveredWallets" in selector
    assert ".map((wallet) => (" in selector
    assert ".filter((wallet)" not in selector


def test_history_and_gate_keep_quality_protection():
    source = read_discovery_source()

    assert (
        source.count(
            f"!{SELECTED_ALLOWED_EXPRESSION}"
        )
        >= 2
    )


def test_ranking_button_allows_observation_wallets():
    source = read_discovery_source()

    assert (
        f"!{ROW_ALLOWED_EXPRESSION}"
        in source
    )