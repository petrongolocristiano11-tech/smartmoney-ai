from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NEW_HEAD = "b6f8d2e4c731"
PREVIOUS_HEAD = "a5e7c1d4b926"
TABLES = {
    "canonical_parser_gen4_copyability_campaigns",
    "canonical_parser_gen4_webhook_receipts",
    "canonical_parser_gen4_copyability_positions",
    "canonical_parser_gen4_copyability_worker_states",
}


def read_dotenv_value(path: Path, name: str) -> str:
    if not path.is_file():
        return ""
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip().lower() != name.lower():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value.strip()
    return ""


def normalize_postgresql_url(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized.startswith("postgres://"):
        normalized = "postgresql+psycopg://" + normalized[len("postgres://") :]
    elif normalized.startswith("postgresql://"):
        normalized = "postgresql+psycopg://" + normalized[len("postgresql://") :]
    if not normalized:
        raise RuntimeError("DATABASE_URL PostgreSQL non disponibile.")
    try:
        parsed = make_url(normalized)
    except Exception as exc:
        raise RuntimeError("DATABASE_URL PostgreSQL non valida.") from exc
    if parsed.get_backend_name() != "postgresql":
        raise RuntimeError("Test migrazione richiesto su PostgreSQL reale.")
    return normalized


def resolve_database_url(project_root: Path = PROJECT_ROOT) -> str:
    environment_value = str(os.environ.pop("DATABASE_URL", "") or "").strip()
    dotenv_value = read_dotenv_value(project_root / ".env", "DATABASE_URL")
    return normalize_postgresql_url(environment_value or dotenv_value)


def run_alembic(target: str, database_url: str) -> None:
    operation = "upgrade" if target == NEW_HEAD else "downgrade"
    child_env = os.environ.copy()
    child_env["DATABASE_URL"] = database_url
    try:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", operation, target],
            cwd=PROJECT_ROOT,
            env=child_env,
            text=True,
            check=False,
        )
    finally:
        child_env.pop("DATABASE_URL", None)
    if result.returncode != 0:
        raise RuntimeError(f"Alembic non riuscito verso {target}.")


def current_revision(engine) -> str | None:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()


def evidence_count(engine) -> int:
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    if not TABLES.issubset(existing):
        return 0
    with engine.connect() as connection:
        return sum(
            int(connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())
            for table in TABLES - {"canonical_parser_gen4_copyability_worker_states"}
        )


def verify_schema(engine) -> None:
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())
    missing = TABLES - existing
    if missing:
        raise AssertionError(f"Tabelle M58-M60 mancanti: {sorted(missing)}")

    receipt_uniques = {
        tuple(item.get("column_names") or [])
        for item in inspector.get_unique_constraints("canonical_parser_gen4_webhook_receipts")
    }
    if ("campaign_db_id", "signature") not in receipt_uniques:
        raise AssertionError("Deduplicazione campaign+signature assente.")

    position_uniques = {
        tuple(item.get("column_names") or [])
        for item in inspector.get_unique_constraints("canonical_parser_gen4_copyability_positions")
    }
    if ("campaign_db_id", "entry_signature") not in position_uniques:
        raise AssertionError("Idempotenza position entry assente.")

    indexes = {
        item.get("name")
        for table in TABLES
        for item in inspector.get_indexes(table)
    }
    required_indexes = {
        "ix_gen4_copy_campaign_status_anchor",
        "ix_gen4_copy_receipt_status_received",
        "ix_gen4_copy_position_open_wallet_token",
        "ix_gen4_copy_worker_lease",
    }
    if not required_indexes.issubset(indexes):
        raise AssertionError(
            f"Indici M58-M60 mancanti: {sorted(required_indexes - indexes)}"
        )

    receipt_fks = inspector.get_foreign_keys("canonical_parser_gen4_webhook_receipts")
    if not any(
        item.get("referred_table") == "canonical_parser_gen4_copyability_campaigns"
        for item in receipt_fks
    ):
        raise AssertionError("FK receipt->campaign assente.")


def main() -> None:
    database_url = resolve_database_url()
    engine = create_engine(database_url, future=True)
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Test migrazione richiesto su PostgreSQL reale.")

    before = current_revision(engine)
    if before not in {PREVIOUS_HEAD, NEW_HEAD}:
        raise RuntimeError(f"Head iniziale inattesa: {before}")

    with engine.connect() as connection:
        forward_campaign_before = connection.execute(
            text(
                "SELECT campaign_id FROM canonical_parser_gen4_forward_campaigns "
                "WHERE status='ACTIVE' ORDER BY anchor_at DESC LIMIT 1"
            )
        ).scalar_one_or_none()

    if before == PREVIOUS_HEAD:
        run_alembic(NEW_HEAD, database_url)
    if current_revision(engine) != NEW_HEAD:
        raise AssertionError("Upgrade M58-M60 non ha raggiunto la head prevista.")
    verify_schema(engine)

    if evidence_count(engine) == 0:
        run_alembic(PREVIOUS_HEAD, database_url)
        if current_revision(engine) != PREVIOUS_HEAD:
            raise AssertionError("Downgrade M58-M60 non ha raggiunto a5e7c1d4b926.")
        remaining = TABLES & set(inspect(engine).get_table_names())
        if remaining:
            raise AssertionError(f"Tabelle rimaste dopo downgrade: {sorted(remaining)}")
        run_alembic(NEW_HEAD, database_url)
        verify_schema(engine)
        roundtrip = "UPGRADE_DOWNGRADE_UPGRADE_OK"
    else:
        roundtrip = "DOWNGRADE_SKIPPED_EVIDENCE_PRESENT"

    with engine.connect() as connection:
        forward_campaign_after = connection.execute(
            text(
                "SELECT campaign_id FROM canonical_parser_gen4_forward_campaigns "
                "WHERE status='ACTIVE' ORDER BY anchor_at DESC LIMIT 1"
            )
        ).scalar_one_or_none()
    if forward_campaign_before != forward_campaign_after:
        raise AssertionError("La campagna forward attiva è cambiata durante la migrazione.")

    print("GEN4_COPYABILITY_POSTGRESQL_MIGRATION=OK")
    print(f"ALEMBIC_HEAD={current_revision(engine)}")
    print(f"ROUNDTRIP={roundtrip}")
    print(f"FORWARD_CAMPAIGN_PRESERVED={forward_campaign_after or 'NONE'}")
    print("DATABASE_URL=REDACTED")


if __name__ == "__main__":
    main()
