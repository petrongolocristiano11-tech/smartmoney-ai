from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

from backend.app.database.base import Base  # noqa: E402
from backend.app.main import app  # noqa: E402

REVISION = "f4d6a9c2b813"
TABLES = {
    "canonical_parser_gen4_forward_campaigns",
    "canonical_parser_gen4_forward_cycles",
    "canonical_parser_gen4_forward_decisions",
}
ROUTES = {
    "/integrity/parser-gen4-forward/status",
    "/integrity/parser-gen4-forward/preview",
    "/integrity/parser-gen4-forward/start",
    "/integrity/parser-gen4-forward/cycle",
    "/integrity/parser-gen4-forward/stop",
    "/integrity/parser-gen4-forward/campaigns/{campaign_id}",
}


def main() -> int:
    missing_tables = sorted(TABLES - set(Base.metadata.tables))
    if missing_tables:
        raise SystemExit(f"Tabelle M52-M53 non registrate: {missing_tables}")

    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision(REVISION)
    if revision.down_revision != "e3b5c8d1f297":
        raise SystemExit(f"Parent Alembic inatteso: {revision.down_revision}")
    if scripts.get_heads() != [REVISION]:
        raise SystemExit(f"Alembic heads inattese: {scripts.get_heads()}")

    schema = app.openapi()
    paths = set(schema.get("paths", {}))
    missing_routes = sorted(ROUTES - paths)
    if missing_routes:
        raise SystemExit(f"Route OpenAPI M52-M53 mancanti: {missing_routes}")

    service = Path(
        "backend/app/services/blockchain_parser_gen4_forward_shadow_service.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "JupiterSwapClient(",
        "httpx.",
        "requests.",
        "send_transaction",
        "sign_transaction",
        "execute_permit_bound_paper",
        "run_live_stream_worker",
    )
    found = [value for value in forbidden if value in service]
    if found:
        raise SystemExit(f"Connessioni vietate nel servizio forward: {found}")

    config_source = Path("backend/app/core/config.py").read_text(encoding="utf-8")
    env_source = Path(".env.example").read_text(encoding="utf-8")
    if "CANONICAL_PARSER_GEN4_FORWARD_ENABLED: bool = False" not in config_source:
        raise SystemExit("Flag forward non disabilitato di default nel config.")
    if "CANONICAL_PARSER_GEN4_FORWARD_ENABLED=false" not in env_source:
        raise SystemExit("Flag forward non disabilitato di default in .env.example.")

    print(f"Alembic head M52-M53: {REVISION}")
    print("Tabelle forward: OK")
    print("OpenAPI M52-M53: OK")
    print("Safety contract: metadata-only, no Helius/Jupiter/paper/LIVE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
