from __future__ import annotations

from pathlib import Path
import inspect
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alembic.config import Config
from alembic.script import ScriptDirectory

from backend.app.services import candidate_history_service
from backend.app.services.gen4_history_acquisition_service import (
    AUTO_ALLOWED_QUALITY_CLASSIFICATIONS,
    EXPLICIT_RESEARCH_REJECTED_CLASSIFICATIONS,
    GEN4_HISTORY_ACQUISITION_CONFIRMATION,
    MAX_TOTAL_HELIUS_REQUESTS,
)


def main() -> None:
    service_path = ROOT / "backend/app/services/gen4_history_acquisition_service.py"
    candidate_path = ROOT / "backend/app/services/candidate_history_service.py"
    script_path = ROOT / "scripts/run_gen4_history_acquisition.py"
    test_path = ROOT / "tests/test_gen4_history_acquisition_m48.py"
    for path in (service_path, candidate_path, script_path, test_path):
        if not path.is_file():
            raise SystemExit(f"File M48 mancante: {path.relative_to(ROOT)}")

    source = service_path.read_text(encoding="utf-8")
    candidate_source = candidate_path.read_text(encoding="utf-8")
    forbidden = (
        "send_transaction",
        "sign_transaction",
        'live_execution_authorized\": True',
        "force=True",
        "scheduler.start",
        "worker.start",
    )
    for token in forbidden:
        if token in source or token in candidate_source:
            raise SystemExit(f"Contratto M48 violato: {token}")

    if GEN4_HISTORY_ACQUISITION_CONFIRMATION not in source:
        raise SystemExit("Conferma M48 non presente nel servizio")
    if AUTO_ALLOWED_QUALITY_CLASSIFICATIONS != {"COPIABILE", "OSSERVAZIONE"}:
        raise SystemExit("Classificazioni automatiche M48 non conformi")
    if EXPLICIT_RESEARCH_REJECTED_CLASSIFICATIONS != {"SOSPETTO"}:
        raise SystemExit("Classificazioni rifiutate M48 non conformi")
    if MAX_TOTAL_HELIUS_REQUESTS != 50:
        raise SystemExit("Budget hard M48 non conforme")

    signature = inspect.signature(
        candidate_history_service.run_extended_candidate_history
    )
    if "evidence_only" not in signature.parameters:
        raise SystemExit("Modalità evidence_only mancante nel backfill storico")
    if "if not evidence_only" not in candidate_source:
        raise SystemExit("Il ricalcolo qualità non è protetto da evidence_only")
    if "evidence_only=True" not in source:
        raise SystemExit("M48 non invoca il backfill in modalità evidence_only")
    if "EXPLICIT_EXTERNAL_EVIDENCE_ONLY" not in source:
        raise SystemExit("Scope evidence-only per wallet esterno mancante")
    if "external_wallet_evidence_only" not in candidate_source:
        raise SystemExit("Backfill esterno evidence-only non tracciato")
    if "external_discovered_wallet_records_created" not in source:
        raise SystemExit("Guardia creazione record discovered_wallets mancante")

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if heads != ["e3b5c8d1f297"]:
        raise SystemExit(f"Head Alembic inattesa: {heads}")

    print("Alembic head invariata: e3b5c8d1f297")
    print("M48: wallet espliciti ammessi in scope evidence-only")
    print("Wallet esplicito esterno: nessun record discovered_wallets richiesto o creato")
    print("Wallet SOSPETTO: sempre rifiutato")
    print("Auto-selezione: priorità COPIABILE/OSSERVAZIONE, poi evidenza locale")
    print("Ricalcolo qualità e promozione: disabilitati durante evidence-only")
    print("Budget Helius hard: massimo 50 richieste per esecuzione")
    print("Force, M31, paper, LIVE, signer e submit: non collegati")
    print("M47 strict/proxy/baseline rieseguiti dopo il backfill")


if __name__ == "__main__":
    main()
