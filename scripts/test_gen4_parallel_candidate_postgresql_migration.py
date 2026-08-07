from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NEW_HEAD = "c8a1f3d6e942"
PREVIOUS_HEAD = "b6f8d2e4c731"
TABLE = "canonical_parser_gen4_copyability_campaigns"


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
    parsed = make_url(normalized)
    if parsed.get_backend_name() != "postgresql":
        raise RuntimeError("Test migrazione richiesto su PostgreSQL reale.")
    return normalized


def resolve_database_url() -> str:
    environment_value = str(os.environ.get("DATABASE_URL") or "").strip()
    dotenv_value = read_dotenv_value(PROJECT_ROOT / ".env", "DATABASE_URL")
    return normalize_postgresql_url(environment_value or dotenv_value)


def run_alembic(operation: str, target: str, database_url: str) -> None:
    child_env = os.environ.copy()
    child_env["DATABASE_URL"] = database_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", operation, target],
        cwd=PROJECT_ROOT,
        env=child_env,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Alembic {operation} non riuscito verso {target}.")


def current_revision(engine) -> str | None:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()


def campaign_snapshot(engine) -> list[dict]:
    """Snapshot all existing rows; zero rows is a valid local baseline."""
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                f"""
                SELECT campaign_id, forward_campaign_db_id, status, verdict,
                       frozen_wallets, anchor_at, minimum_complete_at,
                       receipt_count, duplicate_receipt_count,
                       recovery_receipt_count, processed_receipt_count,
                       failed_receipt_count, ignored_receipt_count,
                       buy_signal_count, sell_signal_count,
                       executable_entry_count, rejected_entry_count,
                       open_position_count, closed_trade_count
                FROM {TABLE}
                ORDER BY id ASC
                """
            )
        ).mappings().all()
    values: list[dict] = []
    for row in rows:
        value = dict(row)
        wallets = value.get("frozen_wallets")
        if isinstance(wallets, str):
            value["frozen_wallets"] = json.loads(wallets)
        values.append(value)
    return values


def verify_schema(engine) -> None:
    inspector = inspect(engine)
    columns = {item["name"]: item for item in inspector.get_columns(TABLE)}
    required = {"campaign_role", "candidate_key", "selection_snapshot"}
    if not required.issubset(columns):
        raise AssertionError(f"Colonne M61 mancanti: {sorted(required - set(columns))}")
    if columns["campaign_role"]["nullable"]:
        raise AssertionError("campaign_role deve essere NOT NULL")
    if columns["candidate_key"]["nullable"]:
        raise AssertionError("candidate_key deve essere NOT NULL")

    uniques = {
        item.get("name"): tuple(item.get("column_names") or [])
        for item in inspector.get_unique_constraints(TABLE)
    }
    if uniques.get("uq_gen4_copy_campaign_candidate_key") != ("candidate_key",):
        raise AssertionError("Unique candidate_key M61 assente")
    if "uq_gen4_copy_campaign_forward" in uniques:
        raise AssertionError("Vecchia unique forward_campaign_db_id ancora presente")

    index_rows = {item.get("name"): item for item in inspector.get_indexes(TABLE)}
    if "ix_gen4_copy_campaign_role_status" not in index_rows:
        raise AssertionError("Indice campaign_role+status M61 assente")
    primary_unique = index_rows.get("uq_gen4_copy_primary_forward")
    if not primary_unique or primary_unique.get("unique") is not True:
        raise AssertionError("Unique parziale della campagna PRIMARY_FORWARD assente")

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                f"""
                SELECT campaign_role, candidate_key, selection_snapshot
                FROM {TABLE}
                ORDER BY id
                """
            )
        ).mappings().all()
    for row in rows:
        if row["campaign_role"] != "PRIMARY_FORWARD":
            raise AssertionError("Backfill campaign_role esistente non conservativo")
        if len(str(row["candidate_key"] or "")) != 64:
            raise AssertionError("Backfill candidate_key non valido")
        if row["selection_snapshot"] is None:
            raise AssertionError("selection_snapshot esistente nullo")


def main() -> None:
    database_url = resolve_database_url()
    engine = create_engine(database_url, future=True)
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Test migrazione richiesto su PostgreSQL reale.")

    before_revision = current_revision(engine)
    if before_revision not in {PREVIOUS_HEAD, NEW_HEAD}:
        raise RuntimeError(f"Head iniziale inattesa: {before_revision}")
    before = campaign_snapshot(engine)

    if before_revision == PREVIOUS_HEAD:
        run_alembic("upgrade", NEW_HEAD, database_url)
    if current_revision(engine) != NEW_HEAD:
        raise AssertionError("Upgrade M61 non ha raggiunto la head prevista")
    verify_schema(engine)
    after_upgrade = campaign_snapshot(engine)
    if before != after_upgrade:
        raise AssertionError("Le righe copyability esistenti sono cambiate durante upgrade M61")

    with engine.connect() as connection:
        candidate_count = int(
            connection.execute(
                text(
                    f"SELECT COUNT(*) FROM {TABLE} "
                    "WHERE campaign_role='QUALIFIED_CANDIDATE'"
                )
            ).scalar_one()
            or 0
        )

    if candidate_count == 0:
        run_alembic("downgrade", PREVIOUS_HEAD, database_url)
        if current_revision(engine) != PREVIOUS_HEAD:
            raise AssertionError("Downgrade M61 non ha raggiunto b6f8d2e4c731")
        if campaign_snapshot(engine) != before:
            raise AssertionError("Righe copyability cambiate durante downgrade M61")
        run_alembic("upgrade", NEW_HEAD, database_url)
        verify_schema(engine)
        if campaign_snapshot(engine) != before:
            raise AssertionError("Righe copyability cambiate nel roundtrip M61")
        roundtrip = "UPGRADE_DOWNGRADE_UPGRADE_OK"
    else:
        roundtrip = "DOWNGRADE_SKIPPED_CANDIDATE_EVIDENCE_PRESENT"

    print("GEN4_PARALLEL_CANDIDATE_POSTGRESQL_MIGRATION=OK")
    print(f"ALEMBIC_HEAD={current_revision(engine)}")
    print(f"ROUNDTRIP={roundtrip}")
    print(f"COPYABILITY_CAMPAIGNS_BEFORE={len(before)}")
    print("COPYABILITY_ROWS_PRESERVED=YES")
    if before:
        print(f"FIRST_EXISTING_CAMPAIGN_ID={before[0]['campaign_id']}")
    else:
        print("LOCAL_COPYABILITY_STATE=EMPTY_VALID_BASELINE")
    print("DATABASE_URL=REDACTED")


if __name__ == "__main__":
    main()
