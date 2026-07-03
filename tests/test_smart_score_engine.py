from backend.app.services.smart_score_engine import clamp


def test_clamp_middle_value():
    assert clamp(50) == 50


def test_clamp_minimum():
    assert clamp(-10) == 0


def test_clamp_maximum():
    assert clamp(150) == 100 