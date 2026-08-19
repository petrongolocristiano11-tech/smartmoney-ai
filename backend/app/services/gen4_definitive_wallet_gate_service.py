from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from backend.app.services.gen4_closed_trade_readonly_audit_service import (
    M64_AUDIT_VERSION,
    M64_EXPECTED_PARSER_VERSION,
    M64_EXPECTED_POLICY_VERSION,
    M64_OFFICIAL_REALTIME_TRADES,
    M64_TARGET_RECONSTRUCTED_TRADES,
    calculate_trade_metrics,
    canonical_sha256,
    file_sha256,
    write_json_atomic,
)


M65_GATE_VERSION = "canonical-parser-gen4-definitive-wallet-qualification-gate/1"
M65_SCOPE = "M65_GEN4_DEFINITIVE_WALLET_QUALIFICATION_GATE_READ_ONLY"
M65_TARGET_COMBINED_TRADES = 100
M65_RUN_CONFIRMATION = "RUN_M65_GEN4_DEFINITIVE_WALLET_QUALIFICATION_GATE"

M65_DEFAULT_POLICY: dict[str, Any] = {
    "policy_version": M65_GATE_VERSION,
    "minimum_combined_closed_trades": 100,
    "minimum_profit_factor": 1.20,
    "maximum_drawdown_percent": 20.0,
    "minimum_recent_closed_trades": 17,
    "minimum_recent_profit_factor": 1.00,
    "maximum_recent_drawdown_percent": 20.0,
    "minimum_unique_tokens": 5,
    "maximum_token_trade_concentration_percent": 40.0,
    "require_positive_net_pnl_after_removing_best_trade": True,
    "stability_window_size": 20,
    "minimum_positive_stability_windows": 3,
    "minimum_worst_stability_window_profit_factor": 0.70,
    "maximum_official_entry_reject_rate_percent": 20.0,
    "require_zero_open_positions": True,
    "require_complete_public_history": True,
    "require_complete_cutoff_batch_sensitivity": True,
    "canary_minimum_observation_hours": 24.0,
    "canary_minimum_entry_attempts": 20,
    "canary_minimum_closed_trades": 10,
    "canary_minimum_webhook_coverage_percent": 95.0,
    "canary_minimum_unsigned_build_coverage_percent": 100.0,
    "canary_maximum_entry_reject_rate_percent": 20.0,
    "canary_maximum_p95_end_to_quote_ms": 5000.0,
    "canary_maximum_p95_price_impact_bps": 500.0,
    "canary_maximum_p95_price_deterioration_bps": 1000.0,
    "canary_require_zero_open_positions": True,
    "canary_require_zero_unresolved_failures": True,
}


class M65DefinitiveGateError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _round(value: float | int | None, digits: int = 8) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _as_int(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as error:
        raise M65DefinitiveGateError(f"Valore intero non valido: {name}.") from error


def _as_float(value: Any, name: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as error:
        raise M65DefinitiveGateError(f"Valore numerico non valido: {name}.") from error
    if not math.isfinite(parsed):
        raise M65DefinitiveGateError(f"Valore non finito: {name}.")
    return parsed


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise M65DefinitiveGateError(message)


def _without_hash(value: dict[str, Any], field: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != field}


def _verify_trade_hashes(trades: Iterable[dict[str, Any]], label: str) -> None:
    seen: set[str] = set()
    for index, raw in enumerate(trades, start=1):
        trade = dict(raw)
        signature = str(trade.get("entry_signature") or "")
        _require(bool(signature), f"Firma entrata assente in {label} #{index}.")
        _require(signature not in seen, f"Firma entrata duplicata in {label}: {signature}.")
        seen.add(signature)
        expected = str(trade.get("evidence_sha256") or "")
        _require(len(expected) == 64, f"Hash trade assente in {label} #{index}.")
        actual = canonical_sha256(_without_hash(trade, "evidence_sha256"))
        _require(expected == actual, f"Hash trade non valido in {label} #{index}.")


def _verify_unique_trade_signatures(
    samples: Iterable[tuple[str, Iterable[dict[str, Any]]]],
) -> None:
    owners: dict[str, str] = {}
    for label, trades in samples:
        for trade in trades:
            signature = str(trade.get("entry_signature") or "")
            previous = owners.get(signature)
            _require(
                previous is None,
                f"Firma entrata presente in piu campioni: {signature} "
                f"({previous}, {label}).",
            )
            owners[signature] = label


def _assert_metrics_match(
    stored: dict[str, Any],
    recalculated: dict[str, Any],
    *,
    label: str,
) -> None:
    integer_fields = (
        "closed_trade_count",
        "winning_trades",
        "losing_trades",
        "breakeven_trades",
        "gross_profit_lamports",
        "gross_loss_lamports",
        "net_pnl_lamports",
        "total_cost_lamports",
        "maximum_drawdown_lamports",
    )
    float_fields = (
        "net_return_percent",
        "profit_factor",
        "win_rate_percent",
        "maximum_drawdown_percent",
    )
    for field in integer_fields:
        _require(
            _as_int(stored.get(field), f"{label}.{field}")
            == _as_int(recalculated.get(field), f"recalculated.{label}.{field}"),
            f"Metrica {label}.{field} non riprodotta.",
        )
    for field in float_fields:
        _require(
            abs(
                _as_float(stored.get(field), f"{label}.{field}")
                - _as_float(
                    recalculated.get(field),
                    f"recalculated.{label}.{field}",
                )
            )
            <= 0.000001,
            f"Metrica {label}.{field} non riprodotta.",
        )


def verify_raw_evidence(
    raw_evidence: dict[str, Any],
    *,
    expected_file_sha256: str,
    raw_evidence_path: Path | None = None,
) -> dict[str, Any]:
    _require(
        raw_evidence.get("scope") == "M64_PUBLIC_FINALIZED_RAW_EVIDENCE",
        "Scope raw evidence M64 inatteso.",
    )
    expected_payload_hash = str(raw_evidence.get("payload_sha256") or "")
    _require(len(expected_payload_hash) == 64, "Hash payload raw evidence assente.")
    _require(
        expected_payload_hash
        == canonical_sha256(_without_hash(raw_evidence, "payload_sha256")),
        "Hash payload raw evidence non valido.",
    )
    _require(_as_int(raw_evidence.get("helius_requests"), "helius_requests") == 0, "Raw evidence con richieste Helius.")
    _require(_as_int(raw_evidence.get("backend_posts"), "backend_posts") == 0, "Raw evidence con backend POST.")
    _require(_as_int(raw_evidence.get("database_writes"), "database_writes") == 0, "Raw evidence con scritture database.")
    _require(bool(raw_evidence.get("boundary_reached")), "Confine pubblico non raggiunto.")
    _require(not bool(raw_evidence.get("signature_limit_reached")), "Limite firme raggiunto.")
    _require(not list(raw_evidence.get("unavailable_signatures") or []), "Transazioni pubbliche non disponibili.")
    actual_file_hash = None
    if raw_evidence_path is not None:
        actual_file_hash = file_sha256(raw_evidence_path)
        _require(actual_file_hash == expected_file_sha256, "SHA-256 file raw evidence non coincide con il report M64.")
    return {
        "payload_sha256": expected_payload_hash,
        "file_sha256": actual_file_hash or expected_file_sha256,
        "boundary_reached": True,
        "signature_limit_reached": False,
        "unavailable_signature_count": 0,
    }


def normalize_m64_audit_report(audit_report: dict[str, Any]) -> dict[str, Any]:
    report = dict(audit_report)
    _require(report.get("audit") == "PASS", "Audit M64 non PASS.")
    _require(report.get("audit_version") == M64_AUDIT_VERSION, "Versione audit M64 inattesa.")
    _require(
        report.get("scope") == "M64_GEN4_83_PLUS_RECONSTRUCTED_CLOSED_TRADES_READ_ONLY",
        "Scope audit M64 inatteso.",
    )
    source = dict(report.get("source") or {})
    _require(source.get("parser_version") == M64_EXPECTED_PARSER_VERSION, "Parser M64 inatteso.")
    _require(source.get("policy_version") == M64_EXPECTED_POLICY_VERSION, "Policy Gen4 inattesa.")
    safety = dict(report.get("safety") or {})
    for field in (
        "helius_requests",
        "database_writes",
        "backend_posts",
        "railway_mutations",
        "jupiter_historical_quote_requests",
        "paper_orders",
        "live_orders",
        "signed_transactions",
        "submitted_transactions",
    ):
        _require(_as_int(safety.get(field), f"safety.{field}") == 0, f"Vincolo sicurezza violato: {field}.")
    _require(safety.get("signer_access") is False, "Accesso signer rilevato.")
    _require(safety.get("official_counter_mutated") is False, "Contatore ufficiale mutato.")
    _require(safety.get("recovery_counted_as_realtime_proof") is False, "Recovery contato come prova real-time.")

    integrity = dict(report.get("integrity") or {})
    expected_report_hash = str(integrity.get("report_payload_sha256") or "")
    _require(len(expected_report_hash) == 64, "Hash report M64 assente.")
    _require(
        expected_report_hash == canonical_sha256(_without_hash(report, "integrity")),
        "Hash report M64 non valido.",
    )
    _require(
        integrity.get("full_signatures_preserved") is True,
        "Il report M64 non garantisce le firme complete.",
    )
    _require(
        integrity.get("raw_transaction_hashes_preserved") is True,
        "Il report M64 non garantisce gli hash delle transazioni raw.",
    )

    artifacts = dict(report.get("artifacts") or {})
    source_raw_hash = str(source.get("raw_evidence_sha256") or "")
    artifact_raw_hash = str(artifacts.get("raw_evidence_sha256") or "")
    artifact_raw_name = str(artifacts.get("raw_evidence_filename") or "")
    _require(len(source_raw_hash) == 64, "SHA-256 raw evidence assente nel source M64.")
    _require(len(artifact_raw_hash) == 64, "SHA-256 raw evidence assente negli artifact M64.")
    _require(
        source_raw_hash == artifact_raw_hash,
        "Gli SHA-256 raw evidence del report M64 non coincidono.",
    )
    _require(bool(artifact_raw_name), "Nome raw evidence assente nel report M64.")

    samples = dict(report.get("samples") or {})
    official_sample = dict(samples.get("official_realtime") or {})
    reconstructed_sample = dict(samples.get("reconstructed") or {})
    combined_sample = dict(samples.get("combined_equivalent") or {})
    sensitivity_sample = dict(samples.get("cutoff_complete_batch_sensitivity") or {})
    official_trades = [dict(item) for item in official_sample.get("trades") or []]
    reconstructed_trades = [
        dict(item) for item in reconstructed_sample.get("trades") or []
    ]
    supplemental_trades = [
        dict(item) for item in sensitivity_sample.get("supplemental_trades") or []
    ]
    _require(len(official_trades) == M64_OFFICIAL_REALTIME_TRADES, "Campione ufficiale diverso da 83.")
    _require(len(reconstructed_trades) == M64_TARGET_RECONSTRUCTED_TRADES, "Campione ricostruito diverso da 17.")
    _require(official_sample.get("evidence_class") == "OFFICIAL_REALTIME", "Classe evidenza ufficiale inattesa.")
    _require(
        reconstructed_sample.get("evidence_class")
        == "RECOVERY_ANALYTIC_ONLY_NOT_REALTIME_PROOF",
        "Classe evidenza ricostruita inattesa.",
    )
    _require(bool(reconstructed_sample.get("target_reached")), "Target 17 non raggiunto.")
    _require(bool(combined_sample.get("target_100_reached")), "Target analitico 100 non raggiunto.")
    _require(_as_int(combined_sample.get("closed_trade_count"), "combined.closed_trade_count") == M65_TARGET_COMBINED_TRADES, "Campione combinato diverso da 100.")

    _verify_trade_hashes(official_trades, "official_realtime")
    _verify_trade_hashes(reconstructed_trades, "reconstructed")
    _verify_trade_hashes(supplemental_trades, "supplemental_cutoff_batch")
    _verify_unique_trade_signatures(
        (
            ("official_realtime", official_trades),
            ("reconstructed", reconstructed_trades),
            ("supplemental_cutoff_batch", supplemental_trades),
        )
    )

    official_metrics = calculate_trade_metrics(
        official_trades,
        evidence_quality="EXACT_PRODUCTION_READ_ONLY",
    )
    reconstructed_metrics = calculate_trade_metrics(
        reconstructed_trades,
        evidence_quality="ESTIMATED_SAME_TRANSACTION_ONCHAIN_PROXY",
    )
    combined_trades = official_trades + reconstructed_trades
    combined_metrics = calculate_trade_metrics(
        combined_trades,
        evidence_quality="MIXED_83_EXACT_PLUS_RECONSTRUCTED_PROXY",
    )
    _assert_metrics_match(dict(official_sample.get("metrics") or {}), official_metrics, label="official")
    _assert_metrics_match(dict(reconstructed_sample.get("metrics") or {}), reconstructed_metrics, label="reconstructed")
    _assert_metrics_match(dict(combined_sample.get("metrics") or {}), combined_metrics, label="combined")

    complete_batch_trades = combined_trades + supplemental_trades
    complete_batch_metrics = calculate_trade_metrics(
        complete_batch_trades,
        evidence_quality="MIXED_83_EXACT_PLUS_COMPLETE_CLOSE_BATCH_SENSITIVITY",
    )
    complete_reconstructed_metrics = calculate_trade_metrics(
        reconstructed_trades + supplemental_trades,
        evidence_quality="ESTIMATED_COMPLETE_CUTOFF_CLOSE_BATCH_SENSITIVITY",
    )
    stored_batch_metrics = dict(sensitivity_sample.get("combined_metrics") or {})
    stored_reconstructed_batch_metrics = dict(
        sensitivity_sample.get("reconstructed_metrics") or {}
    )
    _require(bool(stored_batch_metrics), "Metriche sensitivity batch completo assenti.")
    _require(
        bool(stored_reconstructed_batch_metrics),
        "Metriche sensitivity ricostruite batch completo assenti.",
    )
    _assert_metrics_match(
        stored_batch_metrics,
        complete_batch_metrics,
        label="complete_batch",
    )
    _assert_metrics_match(
        stored_reconstructed_batch_metrics,
        complete_reconstructed_metrics,
        label="complete_reconstructed_batch",
    )
    expected_batch_count = M65_TARGET_COMBINED_TRADES + len(supplemental_trades)
    _require(
        _as_int(sensitivity_sample.get("closed_trade_count"), "sensitivity.closed_trade_count")
        == expected_batch_count,
        "Conteggio sensibilita batch non coerente.",
    )
    _require(
        _as_int(
            sensitivity_sample.get("reconstructed_closed_trade_count"),
            "sensitivity.reconstructed_closed_trade_count",
        )
        == M64_TARGET_RECONSTRUCTED_TRADES + len(supplemental_trades),
        "Conteggio ricostruito della sensitivity batch non coerente.",
    )
    _require(
        _as_int(
            sensitivity_sample.get("supplemental_cutoff_batch_trade_count"),
            "sensitivity.supplemental_cutoff_batch_trade_count",
        )
        == len(supplemental_trades),
        "Conteggio supplementare della sensitivity batch non coerente.",
    )
    target_cut_through = bool(
        sensitivity_sample.get("target_cut_through_close_batch")
    )
    _require(
        target_cut_through == bool(supplemental_trades),
        "Flag taglio batch non coerente con i trade supplementari.",
    )

    campaign = dict(report.get("campaign") or {})
    wallet = str(campaign.get("wallet") or "")
    _require(bool(wallet), "Wallet campagna assente.")
    public_rpc = dict(report.get("public_rpc") or {})
    reconstruction = dict(report.get("reconstruction") or {})
    reconstructed_open_positions = list(
        reconstructed_sample.get("open_positions_at_end") or []
    )
    reconstruction_open_positions = list(
        reconstruction.get("open_positions_at_end") or []
    )
    _require(
        canonical_sha256(reconstructed_open_positions)
        == canonical_sha256(reconstruction_open_positions),
        "Posizioni aperte M64 incoerenti fra sample e ricostruzione.",
    )
    _require(
        bool(reconstruction.get("target_cut_through_close_batch"))
        == target_cut_through,
        "Flag taglio batch M64 incoerente fra sample e ricostruzione.",
    )
    return {
        "wallet": wallet,
        "campaign_id": campaign.get("campaign_id"),
        "audit_report_sha256": expected_report_hash,
        "raw_evidence_sha256": source_raw_hash,
        "raw_evidence_filename": artifact_raw_name,
        "official_trades": official_trades,
        "reconstructed_trades": reconstructed_trades,
        "combined_trades": combined_trades,
        "supplemental_cutoff_batch_trades": supplemental_trades,
        "complete_batch_trades": complete_batch_trades,
        "official_metrics": official_metrics,
        "reconstructed_metrics": reconstructed_metrics,
        "combined_metrics": combined_metrics,
        "complete_batch_metrics": complete_batch_metrics,
        "official_entry_reject_rate_percent": official_sample.get(
            "entry_reject_rate_percent"
        ),
        "history_complete": bool(public_rpc.get("history_complete")),
        "target_cut_through_close_batch": target_cut_through,
        "open_positions": reconstructed_open_positions,
        "historical_entry_admission": dict(
            reconstructed_sample.get("historical_entry_admission") or {}
        ),
        "parser_rejected_transaction_count": _as_int(
            (report.get("parser") or {}).get("rejected_transaction_count") or 0,
            "parser.rejected_transaction_count",
        ),
        "campaign_policy": dict(campaign.get("policy_snapshot") or {}),
        "reconstruction": reconstruction,
    }


def _window_metrics(trades: list[dict[str, Any]], size: int) -> list[dict[str, Any]]:
    rows = sorted(
        [dict(item) for item in trades],
        key=lambda item: (
            str(item.get("closed_at") or ""),
            int(item.get("close_sequence") or 0),
            int(item.get("entry_sequence") or 0),
            str(item.get("entry_signal_at") or ""),
            str(item.get("entry_signature") or ""),
        ),
    )
    result: list[dict[str, Any]] = []
    for start in range(0, len(rows), size):
        chunk = rows[start : start + size]
        if len(chunk) < size:
            continue
        metrics = calculate_trade_metrics(
            chunk,
            evidence_quality="M65_STABILITY_WINDOW",
        )
        result.append(
            {
                "window": len(result) + 1,
                "trade_start": start + 1,
                "trade_end": start + len(chunk),
                "net_pnl_lamports": metrics["net_pnl_lamports"],
                "net_return_percent": metrics["net_return_percent"],
                "profit_factor": metrics["profit_factor"],
                "win_rate_percent": metrics["win_rate_percent"],
                "maximum_drawdown_percent": metrics[
                    "maximum_drawdown_percent"
                ],
            }
        )
    return result


def derive_gate_analytics(
    normalized: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    combined = list(normalized["combined_trades"])
    reconstructed = list(normalized["reconstructed_trades"])
    combined_metrics = dict(normalized["combined_metrics"])
    reconstructed_metrics = dict(normalized["reconstructed_metrics"])
    token_counts = Counter(str(item.get("token_mint") or "") for item in combined)
    top_token, top_count = token_counts.most_common(1)[0] if token_counts else (None, 0)
    top_concentration = top_count / len(combined) * 100.0 if combined else 0.0
    best_pnl = max(
        (int(item.get("pnl_lamports") or 0) for item in combined),
        default=0,
    )
    net_without_best = int(combined_metrics["net_pnl_lamports"]) - best_pnl
    stability_windows = _window_metrics(
        combined,
        max(1, int(policy["stability_window_size"])),
    )
    cost_impacts = {
        "slippage_impact_lamports": 0,
        "fee_impact_lamports": 0,
        "total_cost_impact_lamports": 0,
        "interaction_lamports": 0,
    }
    complete_cost_rows = 0
    for trade in reconstructed:
        impact = dict(trade.get("cost_impact") or {})
        if all(impact.get(field) is not None for field in cost_impacts):
            complete_cost_rows += 1
            for field in cost_impacts:
                cost_impacts[field] += int(impact[field])
    no_cost_net = (
        int(reconstructed_metrics["net_pnl_lamports"])
        + cost_impacts["total_cost_impact_lamports"]
        if complete_cost_rows == len(reconstructed)
        else None
    )
    return {
        "combined": combined_metrics,
        "recent_reconstructed": reconstructed_metrics,
        "complete_cutoff_batch": normalized["complete_batch_metrics"],
        "unique_token_count": len(token_counts),
        "top_token_mint": top_token,
        "top_token_trade_count": top_count,
        "top_token_trade_concentration_percent": _round(top_concentration, 8),
        "best_trade_pnl_lamports": best_pnl,
        "net_pnl_without_best_trade_lamports": net_without_best,
        "stability_windows": stability_windows,
        "positive_stability_window_count": sum(
            int(item["net_pnl_lamports"]) > 0 for item in stability_windows
        ),
        "worst_stability_window_profit_factor": min(
            (float(item["profit_factor"]) for item in stability_windows),
            default=0.0,
        ),
        "reconstructed_cost_impact": {
            **cost_impacts,
            "complete_trade_count": complete_cost_rows,
            "no_cost_net_pnl_lamports": no_cost_net,
        },
    }


def _check(
    checks: list[dict[str, Any]],
    failures: list[str],
    *,
    code: str,
    passed: bool,
    actual: Any,
    operator: str,
    threshold: Any,
) -> None:
    checks.append(
        {
            "code": code,
            "status": "PASS" if passed else "FAIL",
            "actual": actual,
            "operator": operator,
            "threshold": threshold,
        }
    )
    if not passed:
        failures.append(code)


def evaluate_canary(
    canary: dict[str, Any] | None,
    *,
    wallet: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    if canary is None:
        return {
            "status": "MISSING",
            "checks": [],
            "failure_reasons": ["REALTIME_CANARY_EVIDENCE_MISSING"],
            "evidence_sha256": None,
        }
    payload = dict(canary)
    _require(payload.get("scope") == "M65_REALTIME_CANARY_EVIDENCE", "Scope canary inatteso.")
    _require(str(payload.get("wallet") or "") == wallet, "Wallet canary diverso dal candidato.")
    expected_hash = str(payload.get("evidence_sha256") or "")
    _require(len(expected_hash) == 64, "Hash canary assente.")
    _require(expected_hash == canonical_sha256(_without_hash(payload, "evidence_sha256")), "Hash canary non valido.")
    safety = dict(payload.get("safety") or {})
    for field in (
        "paper_orders",
        "live_orders",
        "signed_transactions",
        "submitted_transactions",
    ):
        _require(_as_int(safety.get(field), f"canary.safety.{field}") == 0, f"Canary non shadow: {field}.")
    _require(safety.get("signer_access") is False, "Canary con signer access.")
    checks: list[dict[str, Any]] = []
    failures: list[str] = []
    definitions = (
        ("CANARY_OBSERVATION_HOURS_BELOW_MINIMUM", "observation_hours", ">=", "canary_minimum_observation_hours"),
        ("CANARY_ENTRY_ATTEMPTS_BELOW_MINIMUM", "entry_attempt_count", ">=", "canary_minimum_entry_attempts"),
        ("CANARY_CLOSED_TRADES_BELOW_MINIMUM", "closed_trade_count", ">=", "canary_minimum_closed_trades"),
        ("CANARY_WEBHOOK_COVERAGE_BELOW_MINIMUM", "webhook_coverage_percent", ">=", "canary_minimum_webhook_coverage_percent"),
        ("CANARY_UNSIGNED_BUILD_COVERAGE_BELOW_MINIMUM", "unsigned_build_coverage_percent", ">=", "canary_minimum_unsigned_build_coverage_percent"),
        ("CANARY_ENTRY_REJECT_RATE_ABOVE_MAXIMUM", "entry_reject_rate_percent", "<=", "canary_maximum_entry_reject_rate_percent"),
        ("CANARY_END_TO_QUOTE_P95_ABOVE_MAXIMUM", "p95_end_to_quote_ms", "<=", "canary_maximum_p95_end_to_quote_ms"),
        ("CANARY_PRICE_IMPACT_P95_ABOVE_MAXIMUM", "p95_price_impact_bps", "<=", "canary_maximum_p95_price_impact_bps"),
        ("CANARY_PRICE_DETERIORATION_P95_ABOVE_MAXIMUM", "p95_price_deterioration_bps", "<=", "canary_maximum_p95_price_deterioration_bps"),
    )
    for code, field, operator, threshold_field in definitions:
        actual = _as_float(payload.get(field), f"canary.{field}")
        threshold = _as_float(policy[threshold_field], threshold_field)
        passed = actual >= threshold if operator == ">=" else actual <= threshold
        _check(checks, failures, code=code, passed=passed, actual=actual, operator=operator, threshold=threshold)
    if bool(policy["canary_require_zero_open_positions"]):
        actual_open = _as_int(payload.get("open_position_count"), "canary.open_position_count")
        _check(checks, failures, code="CANARY_OPEN_POSITIONS_PRESENT", passed=actual_open == 0, actual=actual_open, operator="==", threshold=0)
    if bool(policy["canary_require_zero_unresolved_failures"]):
        actual_failures = _as_int(payload.get("unresolved_failure_count"), "canary.unresolved_failure_count")
        _check(checks, failures, code="CANARY_UNRESOLVED_FAILURES_PRESENT", passed=actual_failures == 0, actual=actual_failures, operator="==", threshold=0)
    return {
        "status": "PASS" if not failures else "FAIL",
        "checks": checks,
        "failure_reasons": sorted(failures),
        "evidence_sha256": expected_hash,
    }


def evaluate_definitive_wallet_gate(
    audit_report: dict[str, Any],
    *,
    canary_evidence: dict[str, Any] | None = None,
    gate_policy: dict[str, Any] | None = None,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    policy = {**M65_DEFAULT_POLICY, **dict(gate_policy or {})}
    _require(policy.get("policy_version") == M65_GATE_VERSION, "Versione policy gate inattesa.")
    normalized = normalize_m64_audit_report(audit_report)
    analytics = derive_gate_analytics(normalized, policy)
    combined = analytics["combined"]
    recent = analytics["recent_reconstructed"]
    complete_batch = analytics["complete_cutoff_batch"]
    checks: list[dict[str, Any]] = []
    failures: list[str] = []

    _check(checks, failures, code="COMBINED_CLOSED_SAMPLE_BELOW_MINIMUM", passed=int(combined["closed_trade_count"]) >= int(policy["minimum_combined_closed_trades"]), actual=int(combined["closed_trade_count"]), operator=">=", threshold=int(policy["minimum_combined_closed_trades"]))
    _check(checks, failures, code="COMBINED_NET_PNL_NOT_POSITIVE", passed=int(combined["net_pnl_lamports"]) > 0, actual=int(combined["net_pnl_lamports"]), operator=">", threshold=0)
    _check(checks, failures, code="COMBINED_PROFIT_FACTOR_BELOW_MINIMUM", passed=float(combined["profit_factor"]) >= float(policy["minimum_profit_factor"]), actual=float(combined["profit_factor"]), operator=">=", threshold=float(policy["minimum_profit_factor"]))
    _check(checks, failures, code="COMBINED_DRAWDOWN_ABOVE_MAXIMUM", passed=float(combined["maximum_drawdown_percent"]) <= float(policy["maximum_drawdown_percent"]), actual=float(combined["maximum_drawdown_percent"]), operator="<=", threshold=float(policy["maximum_drawdown_percent"]))
    _check(checks, failures, code="RECENT_CLOSED_SAMPLE_BELOW_MINIMUM", passed=int(recent["closed_trade_count"]) >= int(policy["minimum_recent_closed_trades"]), actual=int(recent["closed_trade_count"]), operator=">=", threshold=int(policy["minimum_recent_closed_trades"]))
    _check(checks, failures, code="RECENT_NET_PNL_NOT_POSITIVE", passed=int(recent["net_pnl_lamports"]) > 0, actual=int(recent["net_pnl_lamports"]), operator=">", threshold=0)
    _check(checks, failures, code="RECENT_PROFIT_FACTOR_BELOW_MINIMUM", passed=float(recent["profit_factor"]) >= float(policy["minimum_recent_profit_factor"]), actual=float(recent["profit_factor"]), operator=">=", threshold=float(policy["minimum_recent_profit_factor"]))
    _check(checks, failures, code="RECENT_DRAWDOWN_ABOVE_MAXIMUM", passed=float(recent["maximum_drawdown_percent"]) <= float(policy["maximum_recent_drawdown_percent"]), actual=float(recent["maximum_drawdown_percent"]), operator="<=", threshold=float(policy["maximum_recent_drawdown_percent"]))
    _check(checks, failures, code="UNIQUE_TOKEN_SAMPLE_BELOW_MINIMUM", passed=int(analytics["unique_token_count"]) >= int(policy["minimum_unique_tokens"]), actual=int(analytics["unique_token_count"]), operator=">=", threshold=int(policy["minimum_unique_tokens"]))
    _check(checks, failures, code="TOKEN_TRADE_CONCENTRATION_ABOVE_MAXIMUM", passed=float(analytics["top_token_trade_concentration_percent"]) <= float(policy["maximum_token_trade_concentration_percent"]), actual=float(analytics["top_token_trade_concentration_percent"]), operator="<=", threshold=float(policy["maximum_token_trade_concentration_percent"]))
    if bool(policy["require_positive_net_pnl_after_removing_best_trade"]):
        _check(checks, failures, code="BEST_TRADE_DEPENDENCY_EXCESSIVE", passed=int(analytics["net_pnl_without_best_trade_lamports"]) > 0, actual=int(analytics["net_pnl_without_best_trade_lamports"]), operator=">", threshold=0)
    _check(checks, failures, code="POSITIVE_STABILITY_WINDOWS_BELOW_MINIMUM", passed=int(analytics["positive_stability_window_count"]) >= int(policy["minimum_positive_stability_windows"]), actual=int(analytics["positive_stability_window_count"]), operator=">=", threshold=int(policy["minimum_positive_stability_windows"]))
    _check(checks, failures, code="WORST_STABILITY_WINDOW_PROFIT_FACTOR_BELOW_MINIMUM", passed=float(analytics["worst_stability_window_profit_factor"]) >= float(policy["minimum_worst_stability_window_profit_factor"]), actual=float(analytics["worst_stability_window_profit_factor"]), operator=">=", threshold=float(policy["minimum_worst_stability_window_profit_factor"]))
    reject_rate = _as_float(normalized["official_entry_reject_rate_percent"], "official_entry_reject_rate_percent")
    _check(checks, failures, code="OFFICIAL_ENTRY_REJECT_RATE_ABOVE_MAXIMUM", passed=reject_rate <= float(policy["maximum_official_entry_reject_rate_percent"]), actual=reject_rate, operator="<=", threshold=float(policy["maximum_official_entry_reject_rate_percent"]))
    if bool(policy["require_zero_open_positions"]):
        open_count = len(normalized["open_positions"])
        _check(checks, failures, code="OPEN_POSITIONS_PRESENT", passed=open_count == 0, actual=open_count, operator="==", threshold=0)
    if bool(policy["require_complete_public_history"]):
        _check(checks, failures, code="PUBLIC_HISTORY_INCOMPLETE", passed=bool(normalized["history_complete"]), actual=bool(normalized["history_complete"]), operator="==", threshold=True)
    if bool(policy["require_complete_cutoff_batch_sensitivity"]):
        _check(checks, failures, code="COMPLETE_BATCH_PROFIT_FACTOR_BELOW_MINIMUM", passed=float(complete_batch["profit_factor"]) >= float(policy["minimum_profit_factor"]), actual=float(complete_batch["profit_factor"]), operator=">=", threshold=float(policy["minimum_profit_factor"]))
        _check(checks, failures, code="COMPLETE_BATCH_NET_PNL_NOT_POSITIVE", passed=int(complete_batch["net_pnl_lamports"]) > 0, actual=int(complete_batch["net_pnl_lamports"]), operator=">", threshold=0)

    canary = evaluate_canary(
        canary_evidence,
        wallet=normalized["wallet"],
        policy=policy,
    )
    if failures:
        status = "FAIL_ECONOMIC"
    elif canary["status"] == "MISSING":
        status = "CONDITIONAL_PASS_CANARY_REQUIRED"
    elif canary["status"] == "FAIL":
        status = "FAIL_CANARY"
    else:
        status = "PASS_FOR_MICRO_LIVE_PREPARATION"

    warnings = [
        "RECOVERY_ANALYTIC_SAMPLE_IS_NOT_OFFICIAL_REALTIME_PROOF",
        "HISTORICAL_JUPITER_ENTRY_ADMISSION_UNAVAILABLE_NOT_INVENTED",
    ]
    if normalized["target_cut_through_close_batch"]:
        warnings.append("TARGET_100_CUTS_THROUGH_ONE_CLOSE_BATCH_SENSITIVITY_INCLUDED")
    output: dict[str, Any] = {
        "gate": status,
        "scope": M65_SCOPE,
        "gate_version": M65_GATE_VERSION,
        "evaluated_at_utc": _iso(evaluated_at or utc_now()),
        "candidate": {
            "wallet": normalized["wallet"],
            "campaign_id": normalized["campaign_id"],
            "recommended_state": (
                "RESEARCH_ONLY_RECENT_STABILITY_FAILED"
                if status == "FAIL_ECONOMIC"
                else (
                    "QUALIFIED_FOR_MICRO_LIVE_PREPARATION"
                    if status == "PASS_FOR_MICRO_LIVE_PREPARATION"
                    else (
                        "REALTIME_CANARY_FAILED"
                        if status == "FAIL_CANARY"
                        else "PENDING_REALTIME_CANARY"
                    )
                )
            ),
        },
        "source": {
            "m64_audit_report_sha256": normalized["audit_report_sha256"],
            "m64_raw_evidence_sha256": normalized["raw_evidence_sha256"],
            "official_realtime_trade_count": M64_OFFICIAL_REALTIME_TRADES,
            "reconstructed_analytic_trade_count": M64_TARGET_RECONSTRUCTED_TRADES,
            "combined_equivalent_trade_count": M65_TARGET_COMBINED_TRADES,
            "official_counter_mutated": False,
            "recovery_counted_as_realtime_proof": False,
        },
        "policy": policy,
        "policy_sha256": canonical_sha256(policy),
        "economic_checks": checks,
        "economic_failure_reasons": sorted(set(failures)),
        "canary": canary,
        "warnings": sorted(warnings),
        "analytics": analytics,
        "verdict": {
            "status": status,
            "economic_gate_passed": not failures,
            "realtime_canary_passed": canary["status"] == "PASS",
            "micro_live_preparation_allowed": status
            == "PASS_FOR_MICRO_LIVE_PREPARATION",
            "micro_live_execution_authorized": False,
            "automatic_live_activation": False,
            "signer_authorized": False,
            "next_step": (
                "DISCOVERY_FINAL_COPYABILITY_AWARE"
                if status == "FAIL_ECONOMIC"
                else (
                    "PREPARE_MICRO_LIVE_WITH_EXPLICIT_USER_AUTHORIZATION"
                    if status == "PASS_FOR_MICRO_LIVE_PREPARATION"
                    else (
                        "REMEDIATE_AND_REPEAT_REALTIME_CANARY"
                        if status == "FAIL_CANARY"
                        else "COLLECT_SHORT_REALTIME_CANARY"
                    )
                )
            ),
        },
        "safety": {
            "helius_requests": 0,
            "database_reads": 0,
            "database_writes": 0,
            "backend_posts": 0,
            "jupiter_requests": 0,
            "paper_orders": 0,
            "live_orders": 0,
            "signed_transactions": 0,
            "submitted_transactions": 0,
            "signer_access": False,
        },
    }
    output["integrity"] = {
        "decision_input_sha256": canonical_sha256(
            {
                "audit_report_sha256": normalized["audit_report_sha256"],
                "canary_evidence_sha256": canary["evidence_sha256"],
                "policy_sha256": output["policy_sha256"],
            }
        ),
        "gate_payload_sha256": canonical_sha256(output),
    }
    return output


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise M65DefinitiveGateError(f"JSON non leggibile: {path.name}.") from error
    if not isinstance(value, dict):
        raise M65DefinitiveGateError(f"JSON root non oggetto: {path.name}.")
    return value


__all__ = [
    "M65_DEFAULT_POLICY",
    "M65DefinitiveGateError",
    "M65_GATE_VERSION",
    "M65_RUN_CONFIRMATION",
    "M65_SCOPE",
    "derive_gate_analytics",
    "evaluate_canary",
    "evaluate_definitive_wallet_gate",
    "load_json",
    "normalize_m64_audit_report",
    "verify_raw_evidence",
    "write_json_atomic",
]
