from types import SimpleNamespace

from backend.app.services.candidate_exitability_gate_service import _evaluate


def wallet():
    return SimpleNamespace(wallet_address="W" * 44)


def audit(**overrides):
    data = {
        "run_id": "run",
        "readiness_status": "BLOCKED",
        "readiness_score": 0,
        "summary": {
            "positions_analyzed": 5,
            "current_route_supported_percent": 0,
            "temporal_execution_percent": 0,
            "cache_missing": 5,
        },
        "diagnoses": ["ALL_OPEN_POSITIONS_MISSING_CACHE"],
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def test_hard_block_requires_complete_zero_exit_evidence():
    result = _evaluate(wallet(), audit())
    assert result["status"] == "BLOCKED"
    assert result["hard_blocked"] is True
    assert result["eligible"] is False


def test_partial_evidence_remains_review_not_hard_block():
    result = _evaluate(
        wallet(),
        audit(summary={
            "positions_analyzed": 5,
            "current_route_supported_percent": 20,
            "temporal_execution_percent": 0,
            "cache_missing": 4,
        }),
    )
    assert result["status"] == "REVIEW"
    assert result["hard_blocked"] is False


def test_ready_audit_is_gate_eligible():
    result = _evaluate(
        wallet(),
        audit(
            readiness_status="READY",
            readiness_score=90,
            summary={
                "positions_analyzed": 5,
                "current_route_supported_percent": 90,
                "temporal_execution_percent": 85,
                "cache_missing": 0,
            },
            diagnoses=[],
        ),
    )
    assert result["status"] == "READY"
    assert result["eligible"] is True


def test_missing_audit_requires_analysis():
    result = _evaluate(wallet(), None)
    assert result["status"] == "NON_ANALIZZATO"
    assert result["eligible"] is False
