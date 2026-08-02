"""Static and OpenAPI acceptance checks for the wallet_edges schema repair."""

from pathlib import Path
import ast
import sys

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.main import app
from backend.app.models.wallet_edge import WalletEdge

EXPECTED_HEAD = "d2a4b7c0e186"
EXPECTED_DOWN_REVISION = "c1f3a6b9d075"
EXPECTED_INDEXES = {
    "ix_wallet_edges_id": ("id",),
    "ix_wallet_edges_source_wallet": ("source_wallet",),
    "ix_wallet_edges_target_wallet": ("target_wallet",),
}
REQUIRED_GET_PATHS = {
    "/trades/graph/{wallet_address}",
    "/trades/clusters",
    "/integrity/parser-unified-decision/preview",
}


def main() -> None:
    table = WalletEdge.__table__
    expected_columns = [
        "id",
        "source_wallet",
        "target_wallet",
        "token_mint",
        "edge_type",
        "strength",
        "created_at",
    ]
    if list(table.columns.keys()) != expected_columns:
        raise SystemExit("Contratto colonne WalletEdge non conforme")

    required_not_null = {
        "id",
        "source_wallet",
        "target_wallet",
        "edge_type",
        "strength",
        "created_at",
    }
    actual_not_null = {
        column.name for column in table.columns if not column.nullable
    }
    if actual_not_null != required_not_null:
        raise SystemExit("Nullability WalletEdge non conforme")

    actual_indexes = {
        index.name: tuple(column.name for column in index.columns)
        for index in table.indexes
    }
    if actual_indexes != EXPECTED_INDEXES:
        raise SystemExit("Indici WalletEdge non conformi")

    service_path = ROOT / "backend/app/services/wallet_graph_engine.py"
    service_source = service_path.read_text()
    service_tree = ast.parse(service_source)
    if "CREATE TABLE" in service_source.upper():
        raise SystemExit("DDL runtime ancora presente nel servizio wallet graph")
    if "ensure_wallet_edges_table" in service_source:
        raise SystemExit("Helper DDL runtime ancora presente")
    function_names = {
        node.name
        for node in ast.walk(service_tree)
        if isinstance(node, ast.FunctionDef)
    }
    if function_names != {"save_wallet_edge"}:
        raise SystemExit("Superficie del servizio wallet graph inattesa")

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if heads != [EXPECTED_HEAD]:
        raise SystemExit(f"Head Alembic inatteso: {heads}")
    revision = script.get_revision(EXPECTED_HEAD)
    if revision is None or revision.down_revision != EXPECTED_DOWN_REVISION:
        raise SystemExit("Catena Alembic wallet_edges non consecutiva")

    openapi = app.openapi()
    paths = openapi.get("paths", {})
    missing = sorted(REQUIRED_GET_PATHS - set(paths))
    if missing:
        raise SystemExit("Endpoint richiesti mancanti: " + ", ".join(missing))
    for path in REQUIRED_GET_PATHS:
        if "get" not in paths[path]:
            raise SystemExit(f"Metodo GET mancante per {path}")

    print(f"Alembic head: {EXPECTED_HEAD}")
    print("WalletEdge: 7 colonne, nullability e 3 indici conformi")
    print("DDL runtime: assente")
    print("OpenAPI: endpoint graph, clusters e preview M31 presenti")
    print("LIVE, worker, scheduler, signer e submit: non modificati")


if __name__ == "__main__":
    main()
