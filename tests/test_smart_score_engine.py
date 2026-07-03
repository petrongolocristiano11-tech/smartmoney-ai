from backend.app.services.smart_score_engine import clamp


def test_clamp_middle_value():
    assert clamp(50) == 50


def test_clamp_minimum():
    assert clamp(-10) == 0


def test_clamp_maximum():
    assert clamp(150) == 100


def test_roi_score_normalization():
    roi_percent = 0
    roi_score = clamp((roi_percent + 100) / 2)

    assert roi_score == 50


def test_profit_score_normalization():
    profit_loss_sol = 0
    profit_score = clamp(profit_loss_sol * 10 + 50)

    assert profit_score == 50


def test_activity_score_normalization():
    reliable_positions = 25
    activity_score = clamp(reliable_positions)

    assert activity_score == 25 