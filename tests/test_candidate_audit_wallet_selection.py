from pathlib import Path


def read_discovery_source() -> str:
    return Path(
        "frontend/src/pages/Discovery.jsx"
    ).read_text(encoding="utf-8")


def extract_button(
    source: str,
    visible_text: str,
) -> str:
    text_index = source.find(visible_text)

    assert text_index >= 0, (
        f"Testo pulsante non trovato: {visible_text}"
    )

    button_start = source.rfind(
        "<button",
        0,
        text_index,
    )
    button_end = source.find(
        "</button>",
        text_index,
    )

    assert button_start >= 0
    assert button_end >= 0

    return source[
        button_start:
        button_end + len("</button>")
    ]


def test_audit_selector_lists_all_discovered_wallets():
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


def test_backfill_remains_quality_protected():
    source = read_discovery_source()
    button = extract_button(
        source,
        "Estendi storico",
    )

    assert "runningBackfill" in button
    assert "!candidateWallet" in button
    assert "quality_classification" in button
    assert "COPIABILE" in button
    assert "OSSERVAZIONE" in button


def test_promotion_gate_remains_quality_protected():
    source = read_discovery_source()
    button = extract_button(
        source,
        "Esegui backtest e gate",
    )

    assert "runningBacktest" in button
    assert "!candidateWallet" in button
    assert "quality_classification" in button
    assert "COPIABILE" in button
    assert "OSSERVAZIONE" in button


def test_audit_button_has_no_quality_restriction():
    source = read_discovery_source()
    button = extract_button(
        source,
        "Audit ricostruzione + sensibilita",
    )

    assert "runningReconstructionAudit" in button
    assert "!candidateWallet" in button

    assert "quality_classification" not in button
    assert "COPIABILE" not in button
    assert "OSSERVAZIONE" not in button