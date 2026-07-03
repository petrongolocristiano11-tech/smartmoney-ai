def calculate_win_rate(positions: list[dict]):
    valid_positions = [
        position
        for position in positions
        if position["roi_reliable"]
    ]

    winning_positions = [
        position
        for position in valid_positions
        if position["profit_loss_sol"] > 0
    ]

    total_valid = len(valid_positions)

    if total_valid > 0:
        return (len(winning_positions) / total_valid) * 100

    return 0


def test_win_rate_with_winners_and_losers():
    positions = [
        {"roi_reliable": True, "profit_loss_sol": 1},
        {"roi_reliable": True, "profit_loss_sol": -1},
        {"roi_reliable": True, "profit_loss_sol": 2},
    ]

    assert round(calculate_win_rate(positions), 2) == 66.67


def test_win_rate_ignores_unreliable_positions():
    positions = [
        {"roi_reliable": True, "profit_loss_sol": 1},
        {"roi_reliable": False, "profit_loss_sol": -10},
    ]

    assert calculate_win_rate(positions) == 100


def test_win_rate_no_valid_positions():
    positions = [
        {"roi_reliable": False, "profit_loss_sol": 1},
    ]

    assert calculate_win_rate(positions) == 0 