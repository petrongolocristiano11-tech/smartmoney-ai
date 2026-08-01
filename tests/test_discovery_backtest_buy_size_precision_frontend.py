from pathlib import Path


def test_backtest_buy_size_accepts_and_defaults_to_five_millisols():
    page = Path("frontend/src/pages/Discovery.jsx").read_text(
        encoding="utf-8"
    )

    assert (
        "const [backtestBuySize, setBacktestBuySize] = "
        "useState(0.005);"
    ) in page
    assert (
        'type="number" min="0.001" step="0.001" '
        'inputMode="decimal" value={backtestBuySize}'
    ) in page
    assert 'step="0.01" value={backtestBuySize}' not in page
    assert page.count("fixedBuySizeSol: backtestBuySize") >= 3
