from __future__ import annotations

from typing import Any

from backend.app.services.gen4_zero_helius_final_pre_micro_live_service import (
    canonical_sha256,
)

FORMAL_M74_ADMISSION_VERSION = "gen4-formal-m74-candidate-admission/6"
FORMAL_M74_ADMISSION_SCOPE = "FORMAL_M74_PASS_TO_FASTPATH_CANDIDATE_ADMISSION_DISARMED"
FORMAL_M74_ADMISSION_ARMED = False
FORMAL_M74_AUTOMATIC_WATCHLIST_MUTATION = False
FORMAL_M74_AUTOMATIC_PROVIDER_MUTATION = False
FORMAL_M74_PRE_ADMISSION_BACKFILL = False

R7_FIX1_SCRIPT_SHA256 = "0d773bb72913cd8eded637357b1ac0c78caa7fe119be3ea26e6bfe429e4c9a0f"
R7_FORMAL_REPORT_SHA256 = "4636f386775669ff089c4c8fb4f233d7374afca32bf751f4e1063b589eeaa536"
R7_FORMAL_EVALUATOR = "evaluate_m74_candidate"

R9_MAXYIELD_FORMAL_REPORT_SHA256 = "1b7da834b3bde1d53c20604c30773c06dc84b409ae95f336f8b8b8de82e43ef6"
R9_FORMAL3_ADMISSION_READINESS_REPORT_SHA256 = "b84d106a78d813e0b887c9473c692dcb57a9a89ffe909ab483e01aee8349f095"
R9_FORMAL_M74_ADMISSION_KIND = "R9_FORMAL_M74_PASS_ADMISSION"

R10_MAXYIELD_FORMAL_REPORT_SHA256 = "6c4b012038f02e422af332339de341c67f84b704cf76f127db4b93032db67ed9"
R10_FORMAL_M74_ADMISSION_KIND = "R10_FORMAL_M74_PASS_ADMISSION"
R10_FORMAL_M74_WALLETS = {
    "3eN9mk": "3eN9mkANNFznz3DarFM2CNXyFVUDeLA6qCuCRKwtxecr",
    "5949hD": "5949hDDDHaxoXemTJmVHArL6avYXUxKY8Ad7Tz43GnCg",
    "2Ec754": "2Ec7546mqCuq1PPGSWTaQZ6DdTGWhpPhEuVicJ3sTQnr",
    "HZuErb": "HZuErbBPoSERBg5fte8guGRZjJhdpnKV7J2CwERJkVS4",
}

R12_STATE_SHA256 = "81d7c1aaed13d497e5f523562039bf69597d233cd16b5fab81b32a83fd5e9a0b"
R12_FULL31_REPORT_SHA256 = "004e472a866929c3e55a18e5d4346642a11ebb704a24827ce9ea75cb6be5be31"
R12_FORMAL_M74_ADMISSION_KIND = "R12_FORMAL_M74_PASS_ADMISSION"
R12_FORMAL_M74_WALLETS = {
    "Ayjjfu": "AyjjfuioEs341LrFaivCS6iPV9dXPyP4qCm4Fe2PRCPX",
    "9Epapg": "9EpapgcFUzzDKdBz8XkSecc6PTAvpqB9Fwwk1rr9Rrfx",
    "E9zj6T": "E9zj6T4uZGr44aYruzo3JTvCZtPgRCgTLrPhfJsJjzy2",
    "BQ9YY6": "BQ9YY6BGvxS8gwZhrLsUbtnPBQeL36rBzqE5Xm6mFygd",
}
R12_PENDING_FLAT_M74_ADMISSION_KIND = "R12_M74_QUALIFIED_PENDING_FLAT_ADMISSION"
R12_PENDING_FLAT_M74_WALLETS = {
    "2SJVK1": "2SJVK1Xhz2WWmsFhLHNpP9CM8q1mTwW7EXSVpHgsFJEs",
    "EUukvc": "EUukvcYYyyhujmdBBpzKEjHSfjpahjNP5W3rNtgMrncK",
}

FORMAL_M74_ADMITTED_WALLETS: dict[str, str] = {
    "5PA": "5pAewyzzyf3bbD2MEdvEjTHR9AqfL9wWouEA8ft2ggEV",
    "3UdE": "3UdEqvfFESsjxJ1mJjhevCqvMmLjzTMiyXfiUVaKeFpG",
    "EdNc": "EdNcBDUFQaTxuaaiFfp5Ss4EanvuXtpGV9ZZvFFVRayd",
    "GmRK": "GmRKk85gpi21Bti8z95fp3iWAGycAMJDz7uZKpAw1TF8",
    "3eN9mk": R10_FORMAL_M74_WALLETS["3eN9mk"],
    "5949hD": R10_FORMAL_M74_WALLETS["5949hD"],
    "2Ec754": R10_FORMAL_M74_WALLETS["2Ec754"],
    "HZuErb": R10_FORMAL_M74_WALLETS["HZuErb"],
    "Ayjjfu": R12_FORMAL_M74_WALLETS["Ayjjfu"],
    "9Epapg": R12_FORMAL_M74_WALLETS["9Epapg"],
    "E9zj6T": R12_FORMAL_M74_WALLETS["E9zj6T"],
    "BQ9YY6": R12_FORMAL_M74_WALLETS["BQ9YY6"],
}


PENDING_FLAT_M74_TARGETED_REPORT_SHA256 = "e1f8aab7fdbeff94fd8927dba55c03fb4d564375bdbd332a9e413b70d945b8e6"
PENDING_FLAT_M74_ROOT_CAUSE_REPORT_SHA256 = "be808e1a2b8cd7a2855629b6f36e9be5bcb6f8bfc7260878d148c1c6be9e9813"
PENDING_FLAT_M74_R8_MAXYIELD_REPORT_SHA256 = "4f4ff27b7d78a89ed586a4b21ebf4ab022bd9302122465495734e576a651a35c"
PENDING_FLAT_M74_R4_CURRENT_ROOT_CAUSE_REPORT_SHA256 = "a3943ee1b79a7256f531647e9bf1695da85b219c5b1151eb6ceb1eacff20ed78"
PENDING_FLAT_M74_R2_ADMISSION_READINESS_REPORT_SHA256 = "1e3b9620bcd27a0285ca72afc07da11932adcb919521eb784e7510485deff7c1"
PENDING_FLAT_M74_LEGACY_ADMISSION_KIND = "R7_M74_QUALIFIED_PENDING_FLAT_ADMISSION"
PENDING_FLAT_M74_R8_ADMISSION_KIND = "R8_M74_QUALIFIED_PENDING_FLAT_ADMISSION"
PENDING_FLAT_M74_STATE = "QUALIFIED_PENDING_FLAT"

PENDING_FLAT_M74_ADMITTED_WALLETS: dict[str, str] = {
    "3N7": "3N7aa2Wkg9dEm8kkC4F7M8knExDyEL8Vehu1S9H3NA2K",
    "2MQR": "2mqrindMAjJEQPLhroYWyiYPo5h9iAsahfdd4QtsjwdY",
    "9rDM": "9rDMVCH7mQ9N2PkyHw8KT8wraMhF8tyMz9R631yyL1df",
    "D9gQ": "D9gQ6RhKEpnobPBUdWY5bPQt2p3zGk3iVz6ChpUi2ArA",
    "37uM": "37uM1rp8TK7eVURVRnjtaxGkdJyXjgA9uz83DjApcHvq",
    "2SJVK1": R12_PENDING_FLAT_M74_WALLETS["2SJVK1"],
    "EUukvc": R12_PENDING_FLAT_M74_WALLETS["EUukvc"],
}

# These wallets were evaluated with the unchanged canonical M74 evaluator.
# Their formal result remains FAIL_COMPLETE_HISTORY because the existing M74
# contract includes zero_open_positions.  This registry does NOT rewrite that
# history or claim a formal M74 PASS.  It records the narrower, independently
# verified fact that every M74 economic check except inventory flatness passed,
# and that the five historical positions are quarantined from all fresh
# candidate/full-lifecycle evidence.
PENDING_FLAT_M74_ADMISSION_EVIDENCE: dict[str, dict[str, Any]] = {
    PENDING_FLAT_M74_ADMITTED_WALLETS["3N7"]: {
        "admission_kind": PENDING_FLAT_M74_LEGACY_ADMISSION_KIND,
        "wallet_address": PENDING_FLAT_M74_ADMITTED_WALLETS["3N7"],
        "qualification_state": PENDING_FLAT_M74_STATE,
        "formal_m74_pass": False,
        "formal_m74_status": "FAIL_COMPLETE_HISTORY",
        "formal_evaluator": R7_FORMAL_EVALUATOR,
        "formal_failure_reasons": ["zero_open_positions"],
        "history_complete": True,
        "all_non_flatness_m74_checks_passed": True,
        "flatness_only_blocker": True,
        "closed_trade_count": 157,
        "profit_factor": 3.61359228,
        "net_pnl_sol": 1.525179787,
        "maximum_drawdown_percent": 5.17888299,
        "open_positions": 5,
        "targeted_report_sha256": PENDING_FLAT_M74_TARGETED_REPORT_SHA256,
        "root_cause_report_sha256": PENDING_FLAT_M74_ROOT_CAUSE_REPORT_SHA256,
        "admission_readiness_report_sha256": None,
        "root_cause_classification": "SOURCE_HAS_NOT_SOLD_THE_5_MODEL_POSITIONS",
        "parser_gap_positions": 0,
        "position_turnover": False,
        "historical_open_positions_quarantined": True,
        "historical_open_positions_followed_by_candidate_lane": False,
        "candidate_forward_proof_backfilled": False,
        "m75_pass_claimed": False,
        "m298_pass_claimed": False,
        "gen4_copyability_pass_claimed": False,
        "live_execution_authorized": False,
    },
    PENDING_FLAT_M74_ADMITTED_WALLETS["2MQR"]: {
        "admission_kind": PENDING_FLAT_M74_LEGACY_ADMISSION_KIND,
        "wallet_address": PENDING_FLAT_M74_ADMITTED_WALLETS["2MQR"],
        "qualification_state": PENDING_FLAT_M74_STATE,
        "formal_m74_pass": False,
        "formal_m74_status": "FAIL_COMPLETE_HISTORY",
        "formal_evaluator": R7_FORMAL_EVALUATOR,
        "formal_failure_reasons": ["zero_open_positions"],
        "history_complete": True,
        "all_non_flatness_m74_checks_passed": True,
        "flatness_only_blocker": True,
        "closed_trade_count": 734,
        "profit_factor": 2.97184034,
        "net_pnl_sol": 3.167214088,
        "maximum_drawdown_percent": 3.60728645,
        "open_positions": 5,
        "targeted_report_sha256": PENDING_FLAT_M74_TARGETED_REPORT_SHA256,
        "root_cause_report_sha256": PENDING_FLAT_M74_ROOT_CAUSE_REPORT_SHA256,
        "admission_readiness_report_sha256": None,
        "root_cause_classification": "SOURCE_HAS_NOT_SOLD_THE_5_MODEL_POSITIONS",
        "parser_gap_positions": 0,
        "position_turnover": False,
        "historical_open_positions_quarantined": True,
        "historical_open_positions_followed_by_candidate_lane": False,
        "candidate_forward_proof_backfilled": False,
        "m75_pass_claimed": False,
        "m298_pass_claimed": False,
        "gen4_copyability_pass_claimed": False,
        "live_execution_authorized": False,
    },
    PENDING_FLAT_M74_ADMITTED_WALLETS["9rDM"]: {
        "admission_kind": PENDING_FLAT_M74_R8_ADMISSION_KIND,
        "wallet_address": PENDING_FLAT_M74_ADMITTED_WALLETS["9rDM"],
        "qualification_state": PENDING_FLAT_M74_STATE,
        "formal_m74_pass": False,
        "formal_m74_status": "FAIL_COMPLETE_HISTORY",
        "formal_evaluator": R7_FORMAL_EVALUATOR,
        "formal_failure_reasons": ["zero_open_positions"],
        "history_complete": True,
        "all_non_flatness_m74_checks_passed": True,
        "flatness_only_blocker": True,
        "closed_trade_count": 1193,
        "profit_factor": 100.28787642,
        "net_pnl_sol": 23.492750972,
        "maximum_drawdown_percent": 0.8309446,
        "open_positions": 5,
        "targeted_report_sha256": PENDING_FLAT_M74_R8_MAXYIELD_REPORT_SHA256,
        "root_cause_report_sha256": PENDING_FLAT_M74_R4_CURRENT_ROOT_CAUSE_REPORT_SHA256,
        "admission_readiness_report_sha256": PENDING_FLAT_M74_R2_ADMISSION_READINESS_REPORT_SHA256,
        "root_cause_classification": "SOURCE_HAS_NOT_SOLD_THE_5_MODEL_POSITIONS",
        "parser_gap_positions": 0,
        "position_turnover": False,
        "historical_open_positions_quarantined": True,
        "historical_open_positions_followed_by_candidate_lane": False,
        "candidate_forward_proof_backfilled": False,
        "m75_pass_claimed": False,
        "m298_pass_claimed": False,
        "gen4_copyability_pass_claimed": False,
        "live_execution_authorized": False,
    },
    PENDING_FLAT_M74_ADMITTED_WALLETS["D9gQ"]: {
        "admission_kind": PENDING_FLAT_M74_R8_ADMISSION_KIND,
        "wallet_address": PENDING_FLAT_M74_ADMITTED_WALLETS["D9gQ"],
        "qualification_state": PENDING_FLAT_M74_STATE,
        "formal_m74_pass": False,
        "formal_m74_status": "FAIL_COMPLETE_HISTORY",
        "formal_evaluator": R7_FORMAL_EVALUATOR,
        "formal_failure_reasons": ["zero_open_positions"],
        "history_complete": True,
        "all_non_flatness_m74_checks_passed": True,
        "flatness_only_blocker": True,
        "closed_trade_count": 2122,
        "profit_factor": 28.39894056,
        "net_pnl_sol": 52.078692904,
        "maximum_drawdown_percent": 2.24234512,
        "open_positions": 5,
        "targeted_report_sha256": PENDING_FLAT_M74_R8_MAXYIELD_REPORT_SHA256,
        "root_cause_report_sha256": PENDING_FLAT_M74_R4_CURRENT_ROOT_CAUSE_REPORT_SHA256,
        "admission_readiness_report_sha256": PENDING_FLAT_M74_R2_ADMISSION_READINESS_REPORT_SHA256,
        "root_cause_classification": "SOURCE_HAS_NOT_SOLD_THE_5_MODEL_POSITIONS",
        "parser_gap_positions": 0,
        "position_turnover": False,
        "historical_open_positions_quarantined": True,
        "historical_open_positions_followed_by_candidate_lane": False,
        "candidate_forward_proof_backfilled": False,
        "m75_pass_claimed": False,
        "m298_pass_claimed": False,
        "gen4_copyability_pass_claimed": False,
        "live_execution_authorized": False,
    },
    PENDING_FLAT_M74_ADMITTED_WALLETS["37uM"]: {
        "admission_kind": PENDING_FLAT_M74_R8_ADMISSION_KIND,
        "wallet_address": PENDING_FLAT_M74_ADMITTED_WALLETS["37uM"],
        "qualification_state": PENDING_FLAT_M74_STATE,
        "formal_m74_pass": False,
        "formal_m74_status": "FAIL_COMPLETE_HISTORY",
        "formal_evaluator": R7_FORMAL_EVALUATOR,
        "formal_failure_reasons": ["zero_open_positions"],
        "history_complete": True,
        "all_non_flatness_m74_checks_passed": True,
        "flatness_only_blocker": True,
        "closed_trade_count": 451,
        "profit_factor": 13.1011247,
        "net_pnl_sol": 10.83847028,
        "maximum_drawdown_percent": 1.95599692,
        "open_positions": 5,
        "targeted_report_sha256": PENDING_FLAT_M74_R8_MAXYIELD_REPORT_SHA256,
        "root_cause_report_sha256": PENDING_FLAT_M74_R4_CURRENT_ROOT_CAUSE_REPORT_SHA256,
        "admission_readiness_report_sha256": PENDING_FLAT_M74_R2_ADMISSION_READINESS_REPORT_SHA256,
        "root_cause_classification": "SOURCE_HAS_NOT_SOLD_THE_5_MODEL_POSITIONS",
        "parser_gap_positions": 0,
        "position_turnover": False,
        "historical_open_positions_quarantined": True,
        "historical_open_positions_followed_by_candidate_lane": False,
        "candidate_forward_proof_backfilled": False,
        "m75_pass_claimed": False,
        "m298_pass_claimed": False,
        "gen4_copyability_pass_claimed": False,
        "live_execution_authorized": False,
    },
    PENDING_FLAT_M74_ADMITTED_WALLETS["2SJVK1"]: {
        "admission_kind": R12_PENDING_FLAT_M74_ADMISSION_KIND,
        "wallet_address": PENDING_FLAT_M74_ADMITTED_WALLETS["2SJVK1"],
        "qualification_state": PENDING_FLAT_M74_STATE,
        "formal_m74_pass": False,
        "formal_m74_status": "FAIL_COMPLETE_HISTORY",
        "formal_evaluator": R7_FORMAL_EVALUATOR,
        "formal_failure_reasons": ["zero_open_positions"],
        "history_complete": True,
        "all_non_flatness_m74_checks_passed": True,
        "flatness_only_blocker": True,
        "closed_trade_count": 110,
        "profit_factor": 17.1049541,
        "net_pnl_sol": 0.445744561,
        "maximum_drawdown_percent": 1.34705538,
        "open_positions": 1,
        "r12_state_sha256": R12_STATE_SHA256,
        "r12_full31_report_sha256": R12_FULL31_REPORT_SHA256,
        "root_cause_classification": "R12_FORMAL_FAILURE_ZERO_OPEN_POSITIONS_ONLY",
        "parser_gap_positions": 0,
        "position_turnover": False,
        "historical_open_positions_quarantined": True,
        "historical_open_positions_followed_by_candidate_lane": False,
        "candidate_forward_proof_backfilled": False,
        "m75_pass_claimed": False,
        "m298_pass_claimed": False,
        "gen4_copyability_pass_claimed": False,
        "live_execution_authorized": False,
    },
    PENDING_FLAT_M74_ADMITTED_WALLETS["EUukvc"]: {
        "admission_kind": R12_PENDING_FLAT_M74_ADMISSION_KIND,
        "wallet_address": PENDING_FLAT_M74_ADMITTED_WALLETS["EUukvc"],
        "qualification_state": PENDING_FLAT_M74_STATE,
        "formal_m74_pass": False,
        "formal_m74_status": "FAIL_COMPLETE_HISTORY",
        "formal_evaluator": R7_FORMAL_EVALUATOR,
        "formal_failure_reasons": ["zero_open_positions"],
        "history_complete": True,
        "all_non_flatness_m74_checks_passed": True,
        "flatness_only_blocker": True,
        "closed_trade_count": 428,
        "profit_factor": 5.06734665,
        "net_pnl_sol": 6.502560359,
        "maximum_drawdown_percent": 7.23985754,
        "open_positions": 2,
        "r12_state_sha256": R12_STATE_SHA256,
        "r12_full31_report_sha256": R12_FULL31_REPORT_SHA256,
        "root_cause_classification": "R12_FORMAL_FAILURE_ZERO_OPEN_POSITIONS_ONLY",
        "parser_gap_positions": 0,
        "position_turnover": False,
        "historical_open_positions_quarantined": True,
        "historical_open_positions_followed_by_candidate_lane": False,
        "candidate_forward_proof_backfilled": False,
        "m75_pass_claimed": False,
        "m298_pass_claimed": False,
        "gen4_copyability_pass_claimed": False,
        "live_execution_authorized": False,
    },
}

# Immutable admission evidence copied from the verified R7 formal report.  This
# does not recompute or weaken M74.  It binds the admitted wallet to one exact
# previously-evaluated formal PASS artifact.
FORMAL_M74_ADMISSION_EVIDENCE: dict[str, dict[str, Any]] = {
    FORMAL_M74_ADMITTED_WALLETS["5PA"]: {
        "admission_kind": "R7_FORMAL_M74_PASS_ADMISSION",
        "wallet_address": FORMAL_M74_ADMITTED_WALLETS["5PA"],
        "formal_m74_pass": True,
        "formal_m74_status": "PASS",
        "formal_evaluator": R7_FORMAL_EVALUATOR,
        "r7_fix1_script_sha256": R7_FIX1_SCRIPT_SHA256,
        "r7_formal_report_sha256": R7_FORMAL_REPORT_SHA256,
        "closed_trade_count": 524,
        "history_span_days": 35.00766204,
        "profit_factor": 16.04721544,
        "net_pnl_sol": 9.01787482,
        "maximum_drawdown_percent": 3.31264317,
        "open_positions": 0,
        "historical_evidence_only": True,
        "candidate_forward_proof_backfilled": False,
        "m75_pass_claimed": False,
        "m298_pass_claimed": False,
        "gen4_copyability_pass_claimed": False,
        "live_execution_authorized": False,
    },
    FORMAL_M74_ADMITTED_WALLETS["3UdE"]: {
        "admission_kind": R9_FORMAL_M74_ADMISSION_KIND,
        "wallet_address": FORMAL_M74_ADMITTED_WALLETS["3UdE"],
        "formal_m74_pass": True,
        "formal_m74_status": "PASS",
        "formal_evaluator": R7_FORMAL_EVALUATOR,
        "formal_failure_reasons": [],
        "history_complete": True,
        "r9_maxyield_report_sha256": R9_MAXYIELD_FORMAL_REPORT_SHA256,
        "r9_admission_readiness_report_sha256": R9_FORMAL3_ADMISSION_READINESS_REPORT_SHA256,
        "closed_trade_count": 187,
        "history_span_days": 32.1328125,
        "profit_factor": 34.86653426,
        "net_pnl_sol": 2.432305971,
        "maximum_drawdown_percent": 1.5658988,
        "recent_profit_factor": 13.37938072,
        "recent_net_pnl_sol": 0.188834504,
        "open_positions": 0,
        "historical_evidence_only": True,
        "candidate_forward_proof_backfilled": False,
        "m75_pass_claimed": False,
        "m298_pass_claimed": False,
        "gen4_copyability_pass_claimed": False,
        "live_execution_authorized": False,
    },
    FORMAL_M74_ADMITTED_WALLETS["EdNc"]: {
        "admission_kind": R9_FORMAL_M74_ADMISSION_KIND,
        "wallet_address": FORMAL_M74_ADMITTED_WALLETS["EdNc"],
        "formal_m74_pass": True,
        "formal_m74_status": "PASS",
        "formal_evaluator": R7_FORMAL_EVALUATOR,
        "formal_failure_reasons": [],
        "history_complete": True,
        "r9_maxyield_report_sha256": R9_MAXYIELD_FORMAL_REPORT_SHA256,
        "r9_admission_readiness_report_sha256": R9_FORMAL3_ADMISSION_READINESS_REPORT_SHA256,
        "closed_trade_count": 872,
        "history_span_days": 34.49731481,
        "profit_factor": 15.19200523,
        "net_pnl_sol": 11.460454231,
        "maximum_drawdown_percent": 3.58194619,
        "recent_profit_factor": 999.0,
        "recent_net_pnl_sol": 0.235122344,
        "open_positions": 0,
        "historical_evidence_only": True,
        "candidate_forward_proof_backfilled": False,
        "m75_pass_claimed": False,
        "m298_pass_claimed": False,
        "gen4_copyability_pass_claimed": False,
        "live_execution_authorized": False,
    },
    FORMAL_M74_ADMITTED_WALLETS["GmRK"]: {
        "admission_kind": R9_FORMAL_M74_ADMISSION_KIND,
        "wallet_address": FORMAL_M74_ADMITTED_WALLETS["GmRK"],
        "formal_m74_pass": True,
        "formal_m74_status": "PASS",
        "formal_evaluator": R7_FORMAL_EVALUATOR,
        "formal_failure_reasons": [],
        "history_complete": True,
        "r9_maxyield_report_sha256": R9_MAXYIELD_FORMAL_REPORT_SHA256,
        "r9_admission_readiness_report_sha256": R9_FORMAL3_ADMISSION_READINESS_REPORT_SHA256,
        "closed_trade_count": 339,
        "history_span_days": 33.21300926,
        "profit_factor": 4.21251621,
        "net_pnl_sol": 1.598777065,
        "maximum_drawdown_percent": 3.29388431,
        "recent_profit_factor": 1.14362375,
        "recent_net_pnl_sol": 0.007222638,
        "open_positions": 0,
        "historical_evidence_only": True,
        "candidate_forward_proof_backfilled": False,
        "m75_pass_claimed": False,
        "m298_pass_claimed": False,
        "gen4_copyability_pass_claimed": False,
        "live_execution_authorized": False,
    },
    '3eN9mkANNFznz3DarFM2CNXyFVUDeLA6qCuCRKwtxecr': {'admission_kind': 'R10_FORMAL_M74_PASS_ADMISSION',
     'wallet_address': '3eN9mkANNFznz3DarFM2CNXyFVUDeLA6qCuCRKwtxecr',
     'formal_m74_pass': True,
     'formal_m74_status': 'PASS',
     'formal_evaluator': 'evaluate_m74_candidate',
     'formal_failure_reasons': [],
     'history_complete': True,
     'r10_maxyield_report_sha256': '6c4b012038f02e422af332339de341c67f84b704cf76f127db4b93032db67ed9',
     'closed_trade_count': 407,
     'history_span_days': 44.40025463,
     'profit_factor': 7.51794661,
     'net_pnl_sol': 4.272654457,
     'maximum_drawdown_percent': 4.89104909,
     'recent_profit_factor': 69.76171278,
     'recent_net_pnl_sol': 0.421574898,
     'open_positions': 0,
     'historical_evidence_only': True,
     'candidate_forward_proof_backfilled': False,
     'm75_pass_claimed': False,
     'm298_pass_claimed': False,
     'gen4_copyability_pass_claimed': False,
     'live_execution_authorized': False},
    '5949hDDDHaxoXemTJmVHArL6avYXUxKY8Ad7Tz43GnCg': {'admission_kind': 'R10_FORMAL_M74_PASS_ADMISSION',
     'wallet_address': '5949hDDDHaxoXemTJmVHArL6avYXUxKY8Ad7Tz43GnCg',
     'formal_m74_pass': True,
     'formal_m74_status': 'PASS',
     'formal_evaluator': 'evaluate_m74_candidate',
     'formal_failure_reasons': [],
     'history_complete': True,
     'r10_maxyield_report_sha256': '6c4b012038f02e422af332339de341c67f84b704cf76f127db4b93032db67ed9',
     'closed_trade_count': 290,
     'history_span_days': 42.81204861,
     'profit_factor': 7.6873088,
     'net_pnl_sol': 4.423181493,
     'maximum_drawdown_percent': 6.47376954,
     'recent_profit_factor': 5.81802069,
     'recent_net_pnl_sol': 0.284626514,
     'open_positions': 0,
     'historical_evidence_only': True,
     'candidate_forward_proof_backfilled': False,
     'm75_pass_claimed': False,
     'm298_pass_claimed': False,
     'gen4_copyability_pass_claimed': False,
     'live_execution_authorized': False},
    '2Ec7546mqCuq1PPGSWTaQZ6DdTGWhpPhEuVicJ3sTQnr': {'admission_kind': 'R10_FORMAL_M74_PASS_ADMISSION',
     'wallet_address': '2Ec7546mqCuq1PPGSWTaQZ6DdTGWhpPhEuVicJ3sTQnr',
     'formal_m74_pass': True,
     'formal_m74_status': 'PASS',
     'formal_evaluator': 'evaluate_m74_candidate',
     'formal_failure_reasons': [],
     'history_complete': True,
     'r10_maxyield_report_sha256': '6c4b012038f02e422af332339de341c67f84b704cf76f127db4b93032db67ed9',
     'closed_trade_count': 113,
     'history_span_days': 44.7044213,
     'profit_factor': 3.14772308,
     'net_pnl_sol': 1.301071013,
     'maximum_drawdown_percent': 11.56934437,
     'recent_profit_factor': 7.70150623,
     'recent_net_pnl_sol': 0.316832076,
     'open_positions': 0,
     'historical_evidence_only': True,
     'candidate_forward_proof_backfilled': False,
     'm75_pass_claimed': False,
     'm298_pass_claimed': False,
     'gen4_copyability_pass_claimed': False,
     'live_execution_authorized': False},
    R10_FORMAL_M74_WALLETS["HZuErb"]: {
        "admission_kind": R10_FORMAL_M74_ADMISSION_KIND,
        "wallet_address": R10_FORMAL_M74_WALLETS["HZuErb"],
        "formal_m74_pass": True,
        "formal_m74_status": "PASS",
        "formal_evaluator": R7_FORMAL_EVALUATOR,
        "formal_failure_reasons": [],
        "history_complete": True,
        "r10_maxyield_report_sha256": R10_MAXYIELD_FORMAL_REPORT_SHA256,
        "closed_trade_count": 106,
        "history_span_days": 43.1794213,
        "profit_factor": 4.17764255,
        "net_pnl_sol": 1.061576707,
        "maximum_drawdown_percent": 11.66298993,
        "recent_profit_factor": 1.59215934,
        "recent_net_pnl_sol": 0.04230236,
        "open_positions": 0,
        "historical_evidence_only": True,
        "candidate_forward_proof_backfilled": False,
        "m75_pass_claimed": False,
        "m298_pass_claimed": False,
        "gen4_copyability_pass_claimed": False,
        "live_execution_authorized": False,
    },
    R12_FORMAL_M74_WALLETS["Ayjjfu"]: {
        "admission_kind": R12_FORMAL_M74_ADMISSION_KIND,
        "wallet_address": R12_FORMAL_M74_WALLETS["Ayjjfu"],
        "formal_m74_pass": True,
        "formal_m74_status": "PASS",
        "formal_evaluator": R7_FORMAL_EVALUATOR,
        "formal_failure_reasons": [],
        "history_complete": True,
        "r12_state_sha256": R12_STATE_SHA256,
        "r12_full31_report_sha256": R12_FULL31_REPORT_SHA256,
        "closed_trade_count": 908,
        "history_span_days": 33.70108796,
        "profit_factor": 9.0544759,
        "net_pnl_sol": 9.74119224,
        "maximum_drawdown_percent": 3.53474568,
        "recent_profit_factor": 40.22212925,
        "recent_net_pnl_sol": 0.462493032,
        "open_positions": 0,
        "historical_evidence_only": True,
        "candidate_forward_proof_backfilled": False,
        "m75_pass_claimed": False,
        "m298_pass_claimed": False,
        "gen4_copyability_pass_claimed": False,
        "live_execution_authorized": False,
    },
    R12_FORMAL_M74_WALLETS["9Epapg"]: {
        "admission_kind": R12_FORMAL_M74_ADMISSION_KIND,
        "wallet_address": R12_FORMAL_M74_WALLETS["9Epapg"],
        "formal_m74_pass": True,
        "formal_m74_status": "PASS",
        "formal_evaluator": R7_FORMAL_EVALUATOR,
        "formal_failure_reasons": [],
        "history_complete": True,
        "r12_state_sha256": R12_STATE_SHA256,
        "r12_full31_report_sha256": R12_FULL31_REPORT_SHA256,
        "closed_trade_count": 137,
        "history_span_days": 43.91780093,
        "profit_factor": 40.53450369,
        "net_pnl_sol": 7.561483351,
        "maximum_drawdown_percent": 5.21586748,
        "recent_profit_factor": 172.11365267,
        "recent_net_pnl_sol": 0.875039457,
        "open_positions": 0,
        "historical_evidence_only": True,
        "candidate_forward_proof_backfilled": False,
        "m75_pass_claimed": False,
        "m298_pass_claimed": False,
        "gen4_copyability_pass_claimed": False,
        "live_execution_authorized": False,
    },
    R12_FORMAL_M74_WALLETS["E9zj6T"]: {
        "admission_kind": R12_FORMAL_M74_ADMISSION_KIND,
        "wallet_address": R12_FORMAL_M74_WALLETS["E9zj6T"],
        "formal_m74_pass": True,
        "formal_m74_status": "PASS",
        "formal_evaluator": R7_FORMAL_EVALUATOR,
        "formal_failure_reasons": [],
        "history_complete": True,
        "r12_state_sha256": R12_STATE_SHA256,
        "r12_full31_report_sha256": R12_FULL31_REPORT_SHA256,
        "closed_trade_count": 241,
        "history_span_days": 31.56,
        "profit_factor": 3.99757253,
        "net_pnl_sol": 3.376684679,
        "maximum_drawdown_percent": 9.35405519,
        "recent_profit_factor": 2.29926609,
        "recent_net_pnl_sol": 0.142952729,
        "open_positions": 0,
        "historical_evidence_only": True,
        "candidate_forward_proof_backfilled": False,
        "m75_pass_claimed": False,
        "m298_pass_claimed": False,
        "gen4_copyability_pass_claimed": False,
        "live_execution_authorized": False,
    },
    R12_FORMAL_M74_WALLETS["BQ9YY6"]: {
        "admission_kind": R12_FORMAL_M74_ADMISSION_KIND,
        "wallet_address": R12_FORMAL_M74_WALLETS["BQ9YY6"],
        "formal_m74_pass": True,
        "formal_m74_status": "PASS",
        "formal_evaluator": R7_FORMAL_EVALUATOR,
        "formal_failure_reasons": [],
        "history_complete": True,
        "r12_state_sha256": R12_STATE_SHA256,
        "r12_full31_report_sha256": R12_FULL31_REPORT_SHA256,
        "closed_trade_count": 100,
        "history_span_days": 31.85355324,
        "profit_factor": 1.76269223,
        "net_pnl_sol": 0.188885125,
        "maximum_drawdown_percent": 5.63166457,
        "recent_profit_factor": 2.72777283,
        "recent_net_pnl_sol": 0.060176351,
        "open_positions": 0,
        "historical_evidence_only": True,
        "candidate_forward_proof_backfilled": False,
        "m75_pass_claimed": False,
        "m298_pass_claimed": False,
        "gen4_copyability_pass_claimed": False,
        "live_execution_authorized": False,
    },
}


class FormalM74CandidateAdmissionError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FormalM74CandidateAdmissionError(message)


def validate_formal_m74_admission_registry() -> dict[str, dict[str, Any]]:
    _require(FORMAL_M74_ADMISSION_ARMED is False, "Formal M74 admission must remain disarmed.")
    _require(
        FORMAL_M74_AUTOMATIC_WATCHLIST_MUTATION is False,
        "Formal M74 admission must not mutate the candidate watchlist automatically.",
    )
    _require(
        FORMAL_M74_AUTOMATIC_PROVIDER_MUTATION is False,
        "Formal M74 admission must not mutate provider configuration automatically.",
    )
    _require(FORMAL_M74_PRE_ADMISSION_BACKFILL is False, "Formal M74 backfill must remain disabled.")
    _require(
        set(FORMAL_M74_ADMITTED_WALLETS)
        == {
            "5PA", "3UdE", "EdNc", "GmRK",
            "3eN9mk", "5949hD", "2Ec754", "HZuErb",
            "Ayjjfu", "9Epapg", "E9zj6T", "BQ9YY6",
        },
        "Unexpected formal M74 admission registry labels.",
    )

    expected = {
        "5PA": {
            "admission_kind": "R7_FORMAL_M74_PASS_ADMISSION",
            "closed_trade_count": 524,
            "history_span_days": 35.00766204,
            "profit_factor": 16.04721544,
            "net_pnl_sol": 9.01787482,
            "maximum_drawdown_percent": 3.31264317,
            "recent_profit_factor": None,
            "recent_net_pnl_sol": None,
        },
        "3UdE": {
            "admission_kind": R9_FORMAL_M74_ADMISSION_KIND,
            "closed_trade_count": 187,
            "history_span_days": 32.1328125,
            "profit_factor": 34.86653426,
            "net_pnl_sol": 2.432305971,
            "maximum_drawdown_percent": 1.5658988,
            "recent_profit_factor": 13.37938072,
            "recent_net_pnl_sol": 0.188834504,
        },
        "EdNc": {
            "admission_kind": R9_FORMAL_M74_ADMISSION_KIND,
            "closed_trade_count": 872,
            "history_span_days": 34.49731481,
            "profit_factor": 15.19200523,
            "net_pnl_sol": 11.460454231,
            "maximum_drawdown_percent": 3.58194619,
            "recent_profit_factor": 999.0,
            "recent_net_pnl_sol": 0.235122344,
        },
        "GmRK": {
            "admission_kind": R9_FORMAL_M74_ADMISSION_KIND,
            "closed_trade_count": 339,
            "history_span_days": 33.21300926,
            "profit_factor": 4.21251621,
            "net_pnl_sol": 1.598777065,
            "maximum_drawdown_percent": 3.29388431,
            "recent_profit_factor": 1.14362375,
            "recent_net_pnl_sol": 0.007222638,
        },
    }

    expected.update({'3eN9mk': {'admission_kind': 'R10_FORMAL_M74_PASS_ADMISSION',
                'closed_trade_count': 407,
                'history_span_days': 44.40025463,
                'profit_factor': 7.51794661,
                'net_pnl_sol': 4.272654457,
                'maximum_drawdown_percent': 4.89104909,
                'recent_profit_factor': 69.76171278,
                'recent_net_pnl_sol': 0.421574898},
     '5949hD': {'admission_kind': 'R10_FORMAL_M74_PASS_ADMISSION',
                'closed_trade_count': 290,
                'history_span_days': 42.81204861,
                'profit_factor': 7.6873088,
                'net_pnl_sol': 4.423181493,
                'maximum_drawdown_percent': 6.47376954,
                'recent_profit_factor': 5.81802069,
                'recent_net_pnl_sol': 0.284626514},
     '2Ec754': {'admission_kind': 'R10_FORMAL_M74_PASS_ADMISSION',
                'closed_trade_count': 113,
                'history_span_days': 44.7044213,
                'profit_factor': 3.14772308,
                'net_pnl_sol': 1.301071013,
                'maximum_drawdown_percent': 11.56934437,
                'recent_profit_factor': 7.70150623,
                'recent_net_pnl_sol': 0.316832076},
     'HZuErb': {'admission_kind': 'R10_FORMAL_M74_PASS_ADMISSION',
                'closed_trade_count': 106,
                'history_span_days': 43.1794213,
                'profit_factor': 4.17764255,
                'net_pnl_sol': 1.061576707,
                'maximum_drawdown_percent': 11.66298993,
                'recent_profit_factor': 1.59215934,
                'recent_net_pnl_sol': 0.04230236}})
    expected.update({
        "Ayjjfu": {
            "admission_kind": R12_FORMAL_M74_ADMISSION_KIND,
            "closed_trade_count": 908,
            "history_span_days": 33.70108796,
            "profit_factor": 9.0544759,
            "net_pnl_sol": 9.74119224,
            "maximum_drawdown_percent": 3.53474568,
            "recent_profit_factor": 40.22212925,
            "recent_net_pnl_sol": 0.462493032,
        },
        "9Epapg": {
            "admission_kind": R12_FORMAL_M74_ADMISSION_KIND,
            "closed_trade_count": 137,
            "history_span_days": 43.91780093,
            "profit_factor": 40.53450369,
            "net_pnl_sol": 7.561483351,
            "maximum_drawdown_percent": 5.21586748,
            "recent_profit_factor": 172.11365267,
            "recent_net_pnl_sol": 0.875039457,
        },
        "E9zj6T": {
            "admission_kind": R12_FORMAL_M74_ADMISSION_KIND,
            "closed_trade_count": 241,
            "history_span_days": 31.56,
            "profit_factor": 3.99757253,
            "net_pnl_sol": 3.376684679,
            "maximum_drawdown_percent": 9.35405519,
            "recent_profit_factor": 2.29926609,
            "recent_net_pnl_sol": 0.142952729,
        },
        "BQ9YY6": {
            "admission_kind": R12_FORMAL_M74_ADMISSION_KIND,
            "closed_trade_count": 100,
            "history_span_days": 31.85355324,
            "profit_factor": 1.76269223,
            "net_pnl_sol": 0.188885125,
            "maximum_drawdown_percent": 5.63166457,
            "recent_profit_factor": 2.72777283,
            "recent_net_pnl_sol": 0.060176351,
        },
    })
    _require({k: FORMAL_M74_ADMITTED_WALLETS[k] for k in R10_FORMAL_M74_WALLETS} == R10_FORMAL_M74_WALLETS, "R10 exact wallets drift.")
    _require({k: FORMAL_M74_ADMITTED_WALLETS[k] for k in R12_FORMAL_M74_WALLETS} == R12_FORMAL_M74_WALLETS, "R12 exact wallets drift.")

    registry: dict[str, dict[str, Any]] = {}
    for label, wallet in FORMAL_M74_ADMITTED_WALLETS.items():
        evidence = dict(FORMAL_M74_ADMISSION_EVIDENCE.get(wallet) or {})
        metrics = expected[label]
        _require(evidence.get("wallet_address") == wallet, f"{label} formal M74 wallet evidence mismatch.")
        _require(evidence.get("formal_m74_pass") is True, f"{label} formal M74 PASS evidence missing.")
        _require(evidence.get("formal_m74_status") == "PASS", f"{label} formal M74 status is not PASS.")
        _require(evidence.get("formal_evaluator") == R7_FORMAL_EVALUATOR, f"{label} formal evaluator drift.")
        _require(evidence.get("admission_kind") == metrics["admission_kind"], f"{label} formal admission kind drift.")
        _require(int(evidence.get("closed_trade_count") or 0) == metrics["closed_trade_count"], f"{label} closed count drift.")
        _require(abs(float(evidence.get("history_span_days") or 0.0) - metrics["history_span_days"]) < 1e-12, f"{label} span drift.")
        _require(abs(float(evidence.get("profit_factor") or 0.0) - metrics["profit_factor"]) < 1e-12, f"{label} PF drift.")
        _require(abs(float(evidence.get("net_pnl_sol") or 0.0) - metrics["net_pnl_sol"]) < 1e-12, f"{label} net PnL drift.")
        _require(abs(float(evidence.get("maximum_drawdown_percent") or 0.0) - metrics["maximum_drawdown_percent"]) < 1e-12, f"{label} DD drift.")
        _require(int(evidence.get("open_positions") if evidence.get("open_positions") is not None else -1) == 0, f"{label} formal report must have zero open positions.")
        _require(evidence.get("historical_evidence_only") is True, f"{label} historical evidence boundary missing.")
        _require(evidence.get("candidate_forward_proof_backfilled") is False, f"{label} candidate proof backfill detected.")
        _require(evidence.get("m75_pass_claimed") is False, f"{label} M75 cannot be claimed by M74 admission.")
        _require(evidence.get("m298_pass_claimed") is False, f"{label} M298 cannot be claimed by M74 admission.")
        _require(evidence.get("gen4_copyability_pass_claimed") is False, f"{label} Gen4 copyability PASS cannot be invented.")
        _require(evidence.get("live_execution_authorized") is False, f"{label} LIVE authorization cannot be inherited.")

        if label == "5PA":
            _require(evidence.get("r7_fix1_script_sha256") == R7_FIX1_SCRIPT_SHA256, "5PA R7 FIX1 SHA drift.")
            _require(evidence.get("r7_formal_report_sha256") == R7_FORMAL_REPORT_SHA256, "5PA R7 report SHA drift.")
        elif label in R10_FORMAL_M74_WALLETS:
            _require(evidence.get("history_complete") is True, f"{label} R10 history incomplete.")
            _require(evidence.get("formal_failure_reasons") == [], f"{label} R10 failures present.")
            _require(evidence.get("r10_maxyield_report_sha256") == R10_MAXYIELD_FORMAL_REPORT_SHA256, f"{label} R10 report SHA drift.")
            for key in ("recent_profit_factor", "recent_net_pnl_sol"):
                _require(abs(float(evidence.get(key) or 0.0) - metrics[key]) < 1e-12, f"{label} R10 recent metric drift: {key}")
        elif label in R12_FORMAL_M74_WALLETS:
            _require(evidence.get("history_complete") is True, f"{label} R12 history incomplete.")
            _require(evidence.get("formal_failure_reasons") == [], f"{label} R12 failures present.")
            _require(evidence.get("r12_state_sha256") == R12_STATE_SHA256, f"{label} R12 state SHA drift.")
            _require(evidence.get("r12_full31_report_sha256") == R12_FULL31_REPORT_SHA256, f"{label} R12 FULL31 SHA drift.")
            for key in ("recent_profit_factor", "recent_net_pnl_sol"):
                _require(abs(float(evidence.get(key) or 0.0) - metrics[key]) < 1e-12, f"{label} R12 recent metric drift: {key}")
        else:
            _require(evidence.get("history_complete") is True, f"{label} R9 history must be complete.")
            _require(list(evidence.get("formal_failure_reasons") or []) == [], f"{label} R9 formal failures must be empty.")
            _require(evidence.get("r9_maxyield_report_sha256") == R9_MAXYIELD_FORMAL_REPORT_SHA256, f"{label} R9 maxyield report SHA drift.")
            _require(
                evidence.get("r9_admission_readiness_report_sha256") == R9_FORMAL3_ADMISSION_READINESS_REPORT_SHA256,
                f"{label} R9 admission readiness SHA drift.",
            )
            _require(
                abs(float(evidence.get("recent_profit_factor") or 0.0) - metrics["recent_profit_factor"]) < 1e-12,
                f"{label} recent PF drift.",
            )
            _require(
                abs(float(evidence.get("recent_net_pnl_sol") or 0.0) - metrics["recent_net_pnl_sol"]) < 1e-12,
                f"{label} recent net drift.",
            )
        registry[wallet] = evidence
    return registry


def validate_pending_flat_m74_admission_registry() -> dict[str, dict[str, Any]]:
    _require(
        len(PENDING_FLAT_M74_ADMITTED_WALLETS) == 7,
        "Unexpected pending-flat M74 admission registry size.",
    )
    _require(
        set(PENDING_FLAT_M74_ADMITTED_WALLETS.values()).isdisjoint(
            FORMAL_M74_ADMITTED_WALLETS.values()
        ),
        "Formal PASS and pending-flat M74 registries must be disjoint.",
    )

    expected = {
        "3N7": {
            "admission_kind": PENDING_FLAT_M74_LEGACY_ADMISSION_KIND,
            "closed_trade_count": 157,
            "profit_factor": 3.61359228,
            "net_pnl_sol": 1.525179787,
            "maximum_drawdown_percent": 5.17888299,
            "open_positions": 5,
            "source": "LEGACY",
            "targeted_report_sha256": PENDING_FLAT_M74_TARGETED_REPORT_SHA256,
            "root_cause_report_sha256": PENDING_FLAT_M74_ROOT_CAUSE_REPORT_SHA256,
            "admission_readiness_report_sha256": None,
        },
        "2MQR": {
            "admission_kind": PENDING_FLAT_M74_LEGACY_ADMISSION_KIND,
            "closed_trade_count": 734,
            "profit_factor": 2.97184034,
            "net_pnl_sol": 3.167214088,
            "maximum_drawdown_percent": 3.60728645,
            "open_positions": 5,
            "source": "LEGACY",
            "targeted_report_sha256": PENDING_FLAT_M74_TARGETED_REPORT_SHA256,
            "root_cause_report_sha256": PENDING_FLAT_M74_ROOT_CAUSE_REPORT_SHA256,
            "admission_readiness_report_sha256": None,
        },
        "9rDM": {
            "admission_kind": PENDING_FLAT_M74_R8_ADMISSION_KIND,
            "closed_trade_count": 1193,
            "profit_factor": 100.28787642,
            "net_pnl_sol": 23.492750972,
            "maximum_drawdown_percent": 0.8309446,
            "open_positions": 5,
            "source": "LEGACY",
            "targeted_report_sha256": PENDING_FLAT_M74_R8_MAXYIELD_REPORT_SHA256,
            "root_cause_report_sha256": PENDING_FLAT_M74_R4_CURRENT_ROOT_CAUSE_REPORT_SHA256,
            "admission_readiness_report_sha256": PENDING_FLAT_M74_R2_ADMISSION_READINESS_REPORT_SHA256,
        },
        "D9gQ": {
            "admission_kind": PENDING_FLAT_M74_R8_ADMISSION_KIND,
            "closed_trade_count": 2122,
            "profit_factor": 28.39894056,
            "net_pnl_sol": 52.078692904,
            "maximum_drawdown_percent": 2.24234512,
            "open_positions": 5,
            "source": "LEGACY",
            "targeted_report_sha256": PENDING_FLAT_M74_R8_MAXYIELD_REPORT_SHA256,
            "root_cause_report_sha256": PENDING_FLAT_M74_R4_CURRENT_ROOT_CAUSE_REPORT_SHA256,
            "admission_readiness_report_sha256": PENDING_FLAT_M74_R2_ADMISSION_READINESS_REPORT_SHA256,
        },
        "37uM": {
            "admission_kind": PENDING_FLAT_M74_R8_ADMISSION_KIND,
            "closed_trade_count": 451,
            "profit_factor": 13.1011247,
            "net_pnl_sol": 10.83847028,
            "maximum_drawdown_percent": 1.95599692,
            "open_positions": 5,
            "source": "LEGACY",
            "targeted_report_sha256": PENDING_FLAT_M74_R8_MAXYIELD_REPORT_SHA256,
            "root_cause_report_sha256": PENDING_FLAT_M74_R4_CURRENT_ROOT_CAUSE_REPORT_SHA256,
            "admission_readiness_report_sha256": PENDING_FLAT_M74_R2_ADMISSION_READINESS_REPORT_SHA256,
        },
        "2SJVK1": {
            "admission_kind": R12_PENDING_FLAT_M74_ADMISSION_KIND,
            "closed_trade_count": 110,
            "profit_factor": 17.1049541,
            "net_pnl_sol": 0.445744561,
            "maximum_drawdown_percent": 1.34705538,
            "open_positions": 1,
            "source": "R12",
        },
        "EUukvc": {
            "admission_kind": R12_PENDING_FLAT_M74_ADMISSION_KIND,
            "closed_trade_count": 428,
            "profit_factor": 5.06734665,
            "net_pnl_sol": 6.502560359,
            "maximum_drawdown_percent": 7.23985754,
            "open_positions": 2,
            "source": "R12",
        },
    }

    registry: dict[str, dict[str, Any]] = {}
    for label, wallet in PENDING_FLAT_M74_ADMITTED_WALLETS.items():
        evidence = dict(PENDING_FLAT_M74_ADMISSION_EVIDENCE.get(wallet) or {})
        _require(evidence.get("wallet_address") == wallet, f"{label} pending-flat wallet evidence mismatch.")
        _require(evidence.get("qualification_state") == PENDING_FLAT_M74_STATE, f"{label} pending-flat state drift.")
        _require(evidence.get("formal_m74_pass") is False, f"{label} must not claim formal M74 PASS.")
        _require(evidence.get("formal_m74_status") == "FAIL_COMPLETE_HISTORY", f"{label} formal M74 status drift.")
        _require(evidence.get("formal_evaluator") == R7_FORMAL_EVALUATOR, f"{label} evaluator drift.")
        _require(
            list(evidence.get("formal_failure_reasons") or []) == ["zero_open_positions"],
            f"{label} is not a flatness-only M74 blocker.",
        )
        _require(evidence.get("history_complete") is True, f"{label} history must be complete.")
        _require(evidence.get("all_non_flatness_m74_checks_passed") is True, f"{label} non-flatness M74 checks not proven.")
        _require(evidence.get("flatness_only_blocker") is True, f"{label} flatness-only marker missing.")
        metrics = expected[label]
        _require(
            int(evidence.get("open_positions") or 0) == int(metrics["open_positions"]),
            f"{label} open-position count drift.",
        )
        _require(evidence.get("admission_kind") == metrics["admission_kind"], f"{label} admission kind drift.")
        if metrics["source"] == "R12":
            _require(evidence.get("r12_state_sha256") == R12_STATE_SHA256, f"{label} R12 state SHA drift.")
            _require(evidence.get("r12_full31_report_sha256") == R12_FULL31_REPORT_SHA256, f"{label} R12 FULL31 SHA drift.")
            _require(
                evidence.get("root_cause_classification") == "R12_FORMAL_FAILURE_ZERO_OPEN_POSITIONS_ONLY",
                f"{label} R12 flatness classification drift.",
            )
        else:
            _require(
                evidence.get("targeted_report_sha256") == metrics["targeted_report_sha256"],
                f"{label} targeted report SHA drift.",
            )
            _require(
                evidence.get("root_cause_report_sha256") == metrics["root_cause_report_sha256"],
                f"{label} root-cause report SHA drift.",
            )
            _require(
                evidence.get("admission_readiness_report_sha256") == metrics["admission_readiness_report_sha256"],
                f"{label} admission-readiness report SHA drift.",
            )
            _require(
                evidence.get("root_cause_classification") == "SOURCE_HAS_NOT_SOLD_THE_5_MODEL_POSITIONS",
                f"{label} root-cause classification drift.",
            )
        _require(int(evidence.get("parser_gap_positions") or 0) == 0, f"{label} parser gap present.")
        _require(evidence.get("position_turnover") is False, f"{label} position turnover unexpectedly present.")
        _require(evidence.get("historical_open_positions_quarantined") is True, f"{label} historical positions not quarantined.")
        _require(
            evidence.get("historical_open_positions_followed_by_candidate_lane") is False,
            f"{label} candidate lane must not inherit historical positions.",
        )
        _require(evidence.get("candidate_forward_proof_backfilled") is False, f"{label} candidate proof backfill detected.")
        _require(evidence.get("m75_pass_claimed") is False, f"{label} M75 cannot be claimed.")
        _require(evidence.get("m298_pass_claimed") is False, f"{label} M298 cannot be claimed.")
        _require(evidence.get("gen4_copyability_pass_claimed") is False, f"{label} Gen4 PASS cannot be invented.")
        _require(evidence.get("live_execution_authorized") is False, f"{label} LIVE authorization cannot be inherited.")

        _require(int(evidence.get("closed_trade_count") or 0) == metrics["closed_trade_count"], f"{label} closed count drift.")
        for key in ("profit_factor", "net_pnl_sol", "maximum_drawdown_percent"):
            _require(
                abs(float(evidence.get(key) or 0.0) - float(metrics[key])) < 1e-12,
                f"{label} {key} drift.",
            )
        registry[wallet] = evidence
    return registry


def pending_flat_m74_admitted_wallets() -> dict[str, str]:
    validate_pending_flat_m74_admission_registry()
    return dict(PENDING_FLAT_M74_ADMITTED_WALLETS)


def pending_flat_m74_admission_for_wallet(wallet: str) -> dict[str, Any] | None:
    registry = validate_pending_flat_m74_admission_registry()
    value = registry.get(str(wallet or "").strip())
    return dict(value) if value is not None else None

def formal_m74_admitted_wallets() -> dict[str, str]:
    validate_formal_m74_admission_registry()
    return dict(FORMAL_M74_ADMITTED_WALLETS)


def formal_m74_admission_for_wallet(wallet: str) -> dict[str, Any] | None:
    registry = validate_formal_m74_admission_registry()
    value = registry.get(str(wallet or "").strip())
    return dict(value) if value is not None else None


def build_formal_m74_admission_report() -> dict[str, Any]:
    registry = validate_formal_m74_admission_registry()
    payload: dict[str, Any] = {
        "evaluation": "PASS",
        "scope": FORMAL_M74_ADMISSION_SCOPE,
        "version": FORMAL_M74_ADMISSION_VERSION,
        "armed": False,
        "admitted_wallets": dict(FORMAL_M74_ADMITTED_WALLETS),
        "evidence": registry,
        "pending_flat_admitted_wallets": dict(PENDING_FLAT_M74_ADMITTED_WALLETS),
        "pending_flat_evidence": validate_pending_flat_m74_admission_registry(),
        "next_boundary": {
            "explicit_candidate_watchlist_mutation_required": True,
            "candidate_entry_evidence_must_be_new": True,
            "m300_attempt_floor_unchanged": True,
            "m300_accepted_floor_unchanged": True,
            "m300_quality_limits_unchanged": True,
            "m300_technical_reset_unchanged": True,
            "m298_full_lifecycle_not_started": True,
            "pending_flat_historical_positions_quarantined": True,
            "pending_flat_candidate_evidence_must_start_fresh": True,
        },
        "safety": {
            "database_writes": 0,
            "railway_variable_set": False,
            "provider_mutations": 0,
            "helius_calls": 0,
            "jupiter_requests": 0,
            "pre_admission_backfill": False,
            "gen4_copyability_pass_invented": False,
            "m75_changed": False,
            "m298_changed": False,
            "pam_changed": False,
            "live": False,
            "signer": False,
            "submission": False,
            "paper_orders": 0,
        },
    }
    payload["integrity"] = {"payload_sha256": canonical_sha256(payload)}
    return payload
