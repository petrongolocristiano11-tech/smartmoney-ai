from __future__ import annotations

import inspect

import backend.app.services.gen4_fastpath_shadow_service as fast
import backend.app.services.jupiter_swap_client as jup


def test_r40_known_good_parallel_quote_path_remains_available_after_recovery():
    source = inspect.getsource(jup.JupiterSwapClient.get_quote_and_unsigned_build)
    assert "ThreadPoolExecutor(" in source
    assert '"/order"' in source
    assert '"/build"' in source


def test_r42_candidate_buy_moves_from_r40_parallel_path_to_order_only_shadow():
    source = inspect.getsource(fast.record_fastpath_candidate_notification)
    assert "quote = _candidate_order_only_quote(" in source
    assert "quote = _candidate_entry_quote(" not in source


def test_r40_legacy_quote_still_uses_parallel_order_and_build():
    source = inspect.getsource(jup.JupiterSwapClient.get_quote_and_unsigned_build)
    assert "ThreadPoolExecutor(" in source
    assert '"/order"' in source
    assert '"/build"' in source
    assert "order_future" in source
    assert "build_future" in source


def test_r40_m320_infrastructure_remains_present_but_not_candidate_critical_path():
    source = inspect.getsource(fast.record_fastpath_candidate_notification)
    assert "M320_CANDIDATE_ORDER_DIAGNOSTIC_VERSION" in source
    assert "PENDING_POST_COMMIT_LOW_PRIORITY" in source
    assert "candidate_build_priority" in source
    assert "quote = _candidate_entry_quote(" not in source


def test_r40_build_only_helper_is_not_deleted_for_future_offline_work():
    assert callable(getattr(fast, "_candidate_entry_quote", None))
    assert callable(getattr(jup.JupiterSwapClient, "get_build_priority_unsigned", None))
