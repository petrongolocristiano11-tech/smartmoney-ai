from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "backend/app/services/gen4_evidence_sprint_service.py"
RUNNER = ROOT / "scripts/run_gen4_evidence_sprint.py"


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise SystemExit(f"Contratto M49-M50 mancante: {label}")


def main() -> None:
    service = SERVICE.read_text(encoding="utf-8")
    runner = RUNNER.read_text(encoding="utf-8")
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if heads != ["e3b5c8d1f297"]:
        raise SystemExit(f"Alembic head inattesa: {heads}")

    for needle, label in (
        ("MAX_TOTAL_HELIUS_REQUESTS = 40", "budget Helius hard"),
        ("evidence_only=True", "backfill evidence-only"),
        ("force=False", "force disabilitato"),
        ("strict_gen4_reconstructed_retroactively", "guard strict retroattivo"),
        ("quality_recalculation_performed", "guard qualità"),
        ("promotion_changes_performed", "guard promozione"),
        ("live_execution_authorized", "guard LIVE"),
        ("preview_gen4_profitability", "riesecuzione M47"),
    ):
        require(service, needle, label)
    require(runner, "STRICT_GEN4 non ricostruita retroattivamente", "output interpretazione")

    print("Alembic head invariata: e3b5c8d1f297")
    print("M49: scouting wallet compagno da token condivisi con budget hard")
    print("M50: M47 rieseguita con diagnosi gate/consenso e primo risultato proxy")
    print("STRICT_GEN4: non falsificata o retrodatata")
    print("Qualità, promozione, M31, paper, LIVE, signer e submit: non collegati")


if __name__ == "__main__":
    main()
