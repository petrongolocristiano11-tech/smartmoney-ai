from backend.app.services.roi_engine import MIN_SOL_SPENT_FOR_ROI


def calculate_roi(spent: float, received: float):
    pnl = received - spent

    if spent >= MIN_SOL_SPENT_FOR_ROI:
        roi = (pnl / spent) * 100
        reliable = True
    else:
        roi = 0
        reliable = False

    return roi, reliable


def test_positive_roi():
    roi, reliable = calculate_roi(1.0, 1.5)

    assert reliable is True
    assert roi == 50.0


def test_negative_roi():
    roi, reliable = calculate_roi(2.0, 1.0)

    assert reliable is True
    assert roi == -50.0


def test_unreliable_roi():
    roi, reliable = calculate_roi(0.00001, 1.0)

    assert reliable is False
    assert roi == 0 