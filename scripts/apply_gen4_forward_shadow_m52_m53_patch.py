from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

PROJECT_ROOT_DEFAULT = Path(r"C:\smartmoney-ai")

ENV_BLOCK = """# M52-M53 GEN4 STRICT FORWARD SHADOW CAMPAIGN
CANONICAL_PARSER_GEN4_FORWARD_ENABLED=false
CANONICAL_PARSER_GEN4_FORWARD_TRAINING_DAYS=14
CANONICAL_PARSER_GEN4_FORWARD_MIN_FROZEN_WALLETS=2
CANONICAL_PARSER_GEN4_FORWARD_MAX_FROZEN_WALLETS=20
CANONICAL_PARSER_GEN4_FORWARD_MIN_OBSERVATION_DAYS=21
CANONICAL_PARSER_GEN4_FORWARD_MIN_CLOSED_TRADES=30
CANONICAL_PARSER_GEN4_FORWARD_PROOF_CLOSED_TRADES=100
CANONICAL_PARSER_GEN4_FORWARD_MAX_SOURCE_TRADES_PER_CYCLE=200000
CANONICAL_PARSER_GEN4_FORWARD_MAX_INGESTION_LAG_SECONDS=300
CANONICAL_PARSER_GEN4_FORWARD_MAX_SAFETY_WAIT_MINUTES=30
"""

CONFIG_BLOCK = """    # =========================
    # M52-M53 GEN4 STRICT FORWARD SHADOW CAMPAIGN
    # Metadata-only forward observation; disabled by default; no execution connections.
    # =========================

    CANONICAL_PARSER_GEN4_FORWARD_ENABLED: bool = False
    CANONICAL_PARSER_GEN4_FORWARD_TRAINING_DAYS: int = Field(default=14, ge=3, le=365)
    CANONICAL_PARSER_GEN4_FORWARD_MIN_FROZEN_WALLETS: int = Field(default=2, ge=2, le=100)
    CANONICAL_PARSER_GEN4_FORWARD_MAX_FROZEN_WALLETS: int = Field(default=20, ge=2, le=100)
    CANONICAL_PARSER_GEN4_FORWARD_MIN_OBSERVATION_DAYS: int = Field(default=21, ge=1, le=3650)
    CANONICAL_PARSER_GEN4_FORWARD_MIN_CLOSED_TRADES: int = Field(default=30, ge=1, le=1000000)
    CANONICAL_PARSER_GEN4_FORWARD_PROOF_CLOSED_TRADES: int = Field(default=100, ge=1, le=1000000)
    CANONICAL_PARSER_GEN4_FORWARD_MAX_SOURCE_TRADES_PER_CYCLE: int = Field(default=200000, ge=100, le=2000000)
    CANONICAL_PARSER_GEN4_FORWARD_MAX_INGESTION_LAG_SECONDS: int = Field(default=300, ge=1, le=86400)
    CANONICAL_PARSER_GEN4_FORWARD_MAX_SAFETY_WAIT_MINUTES: int = Field(default=30, ge=1, le=10080)

"""

MODEL_IMPORT_BLOCK = """from backend.app.models.gen4_forward_shadow import (
    CanonicalParserGen4ForwardCampaign,
    CanonicalParserGen4ForwardCycle,
    CanonicalParserGen4ForwardDecision,
)
"""

MODEL_EXPORT_BLOCK = """    \"CanonicalParserGen4ForwardCampaign\",
    \"CanonicalParserGen4ForwardCycle\",
    \"CanonicalParserGen4ForwardDecision\",
"""

SCHEMA_BLOCK = """class CanonicalParserGen4ForwardCampaignStartRequest(BaseModel):
    confirmation: str = Field(default=\"\", max_length=320)
    candidate_wallets: list[str] | None = Field(default=None, max_length=100)
    anchor_at: datetime | None = None
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserGen4ForwardCycleRequest(BaseModel):
    campaign_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default=\"\", max_length=320)
    observed_at: datetime | None = None


class CanonicalParserGen4ForwardCampaignStopRequest(BaseModel):
    campaign_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default=\"\", max_length=320)
    observed_at: datetime | None = None
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


"""

MAIN_SCHEMA_IMPORTS = """    CanonicalParserGen4ForwardCampaignStartRequest,
    CanonicalParserGen4ForwardCycleRequest,
    CanonicalParserGen4ForwardCampaignStopRequest,
"""

MAIN_SERVICE_IMPORT = """from backend.app.services.blockchain_parser_gen4_forward_shadow_service import (
    CanonicalParserGen4ForwardShadowError,
    get_gen4_forward_campaign,
    get_gen4_forward_status,
    preview_gen4_forward_campaign,
    run_gen4_forward_cycle,
    start_gen4_forward_campaign,
    stop_gen4_forward_campaign,
)
"""

MAIN_ENDPOINTS = """# BEGIN M52-M53 GEN4 STRICT FORWARD SHADOW CAMPAIGN
@app.get(\"/integrity/parser-gen4-forward/status\", tags=[\"Blockchain Integrity\"], dependencies=[Depends(require_automation_key)])
def read_gen4_forward_status_endpoint(db: Session = Depends(get_db)):
    return get_gen4_forward_status(db)


@app.get(\"/integrity/parser-gen4-forward/preview\", tags=[\"Blockchain Integrity\"], dependencies=[Depends(require_automation_key)])
def read_gen4_forward_preview_endpoint(
    candidate_wallets: list[str] | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return preview_gen4_forward_campaign(db, candidate_wallets=candidate_wallets)


@app.post(\"/integrity/parser-gen4-forward/start\", tags=[\"Blockchain Integrity\"], dependencies=[Depends(require_automation_key)])
def start_gen4_forward_campaign_endpoint(
    request: CanonicalParserGen4ForwardCampaignStartRequest,
    db: Session = Depends(get_db),
):
    try:
        result = start_gen4_forward_campaign(
            db,
            confirmation=request.confirmation,
            candidate_wallets=request.candidate_wallets,
            anchor_at=request.anchor_at,
            actor_label=request.actor_label,
            note=request.note,
        )
        db.commit()
        return result
    except CanonicalParserGen4ForwardShadowError as exception:
        db.rollback()
        raise HTTPException(
            status_code=exception.status_code,
            detail={\"code\": exception.code, \"message\": str(exception)},
        ) from exception


@app.post(\"/integrity/parser-gen4-forward/cycle\", tags=[\"Blockchain Integrity\"], dependencies=[Depends(require_automation_key)])
def run_gen4_forward_cycle_endpoint(
    request: CanonicalParserGen4ForwardCycleRequest,
    db: Session = Depends(get_db),
):
    try:
        result = run_gen4_forward_cycle(
            db,
            campaign_id=request.campaign_id,
            confirmation=request.confirmation,
            observed_at=request.observed_at,
        )
        db.commit()
        return result
    except CanonicalParserGen4ForwardShadowError as exception:
        db.rollback()
        raise HTTPException(
            status_code=exception.status_code,
            detail={\"code\": exception.code, \"message\": str(exception)},
        ) from exception


@app.post(\"/integrity/parser-gen4-forward/stop\", tags=[\"Blockchain Integrity\"], dependencies=[Depends(require_automation_key)])
def stop_gen4_forward_campaign_endpoint(
    request: CanonicalParserGen4ForwardCampaignStopRequest,
    db: Session = Depends(get_db),
):
    try:
        result = stop_gen4_forward_campaign(
            db,
            campaign_id=request.campaign_id,
            confirmation=request.confirmation,
            observed_at=request.observed_at,
            actor_label=request.actor_label,
            note=request.note,
        )
        db.commit()
        return result
    except CanonicalParserGen4ForwardShadowError as exception:
        db.rollback()
        raise HTTPException(
            status_code=exception.status_code,
            detail={\"code\": exception.code, \"message\": str(exception)},
        ) from exception


@app.get(\"/integrity/parser-gen4-forward/campaigns/{campaign_id}\", tags=[\"Blockchain Integrity\"], dependencies=[Depends(require_automation_key)])
def read_gen4_forward_campaign_endpoint(
    campaign_id: str,
    include_decisions: bool = Query(default=True),
    decision_limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    try:
        return get_gen4_forward_campaign(
            db,
            campaign_id,
            include_decisions=include_decisions,
            decision_limit=decision_limit,
        )
    except CanonicalParserGen4ForwardShadowError as exception:
        raise HTTPException(
            status_code=exception.status_code,
            detail={\"code\": exception.code, \"message\": str(exception)},
        ) from exception
# END M52-M53 GEN4 STRICT FORWARD SHADOW CAMPAIGN
"""


class PatchError(RuntimeError):
    pass


@dataclass
class TextFile:
    path: Path
    text: str
    newline: str
    had_bom: bool


def read_text_file(path: Path) -> TextFile:
    if not path.exists():
        raise PatchError(f"File richiesto mancante: {path}")
    raw = path.read_bytes()
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    decoded = raw.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in decoded else "\n"
    normalized = decoded.replace("\r\n", "\n").replace("\r", "\n")
    return TextFile(path=path, text=normalized, newline=newline, had_bom=had_bom)


def write_text_file(file: TextFile, text: str) -> None:
    rendered = text.replace("\n", file.newline)
    data = rendered.encode("utf-8")
    if file.had_bom:
        data = b"\xef\xbb\xbf" + data
    file.path.write_bytes(data)


def insert_after_once(text: str, anchor: str, addition: str, *, label: str) -> str:
    if addition.strip() in text:
        return text
    count = text.count(anchor)
    if count != 1:
        raise PatchError(f"Anchor {label} atteso una volta, trovato {count}.")
    return text.replace(anchor, anchor + addition, 1)


def insert_before_once(text: str, anchor: str, addition: str, *, label: str) -> str:
    if addition.strip() in text:
        return text
    count = text.count(anchor)
    if count != 1:
        raise PatchError(f"Anchor {label} atteso una volta, trovato {count}.")
    return text.replace(anchor, addition + anchor, 1)


def patch_env(text: str) -> str:
    if "# M52-M53 GEN4 STRICT FORWARD SHADOW CAMPAIGN" in text:
        return text
    return text.rstrip("\n") + "\n\n" + ENV_BLOCK


def patch_config(text: str) -> str:
    if "CANONICAL_PARSER_GEN4_FORWARD_ENABLED" in text:
        return text
    anchor = "    # =========================\n    # CONTROLLED DISCOVERY HYDRATION"
    return insert_before_once(text, anchor, CONFIG_BLOCK, label="config controlled discovery")


def patch_models_init(text: str) -> str:
    if "from backend.app.models.gen4_forward_shadow import (" not in text:
        start = text.find("from backend.app.models.gen4_profitability import (")
        if start < 0:
            raise PatchError("Import gen4_profitability non trovato in models/__init__.py")
        end = text.find("\n)\n", start)
        if end < 0:
            raise PatchError("Chiusura import gen4_profitability non trovata in models/__init__.py")
        end += len("\n)\n")
        text = text[:end] + MODEL_IMPORT_BLOCK + text[end:]
    if '    "CanonicalParserGen4ForwardCampaign",' not in text:
        anchor = '    "CanonicalParserGen4ProfitabilityTrade",\n'
        text = insert_after_once(text, anchor, MODEL_EXPORT_BLOCK, label="models __all__ gen4 profitability")
    return text


def patch_schemas(text: str) -> str:
    if "class CanonicalParserGen4ForwardCampaignStartRequest" in text:
        return text
    anchor = "class CanonicalParserPermitBoundPaperExecutionRequest"
    return insert_before_once(text, anchor, SCHEMA_BLOCK, label="schema permit-bound request")


def patch_main(text: str) -> str:
    if "CanonicalParserGen4ForwardCampaignStartRequest" not in text:
        anchor = "    CanonicalParserGen4ProfitabilityRunRequest,\n"
        text = insert_after_once(text, anchor, MAIN_SCHEMA_IMPORTS, label="main schema import")

    if "from backend.app.services.blockchain_parser_gen4_forward_shadow_service import (" not in text:
        start = text.find("from backend.app.services.blockchain_parser_gen4_profitability_service import (")
        if start < 0:
            raise PatchError("Import service gen4 profitability non trovato in main.py")
        end = text.find("\n)\n", start)
        if end < 0:
            raise PatchError("Chiusura import service gen4 profitability non trovata in main.py")
        end += len("\n)\n")
        text = text[:end] + MAIN_SERVICE_IMPORT + text[end:]

    if "# BEGIN M52-M53 GEN4 STRICT FORWARD SHADOW CAMPAIGN" not in text:
        anchor = "# END M47 GEN4 WALK-FORWARD PROFITABILITY VALIDATION\n"
        text = insert_after_once(text, anchor, "\n" + MAIN_ENDPOINTS, label="main endpoint M47 end")
    return text


def patch_m47_test(text: str) -> str:
    target = '    assert scripts.get_heads() == ["f4d6a9c2b813"]'
    if target in text:
        return text

    pattern = re.compile(
        r'(?m)^\s*assert\s+scripts\.get_heads\(\)\s*==\s*\["[0-9a-f]+"\]\s*$'
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise PatchError(
            f"Assert head Alembic nel test M47 atteso una volta, trovato {len(matches)}."
        )
    match = matches[0]
    return text[: match.start()] + target + text[match.end() :]


PATCHES: tuple[tuple[str, Callable[[str], str]], ...] = (
    (".env.example", patch_env),
    ("backend/app/core/config.py", patch_config),
    ("backend/app/models/__init__.py", patch_models_init),
    ("backend/app/schemas/blockchain_integrity.py", patch_schemas),
    ("backend/app/main.py", patch_main),
    ("tests/test_parser_gen4_profitability_m47.py", patch_m47_test),
)


def run(project_root: Path, *, apply: bool) -> dict[str, object]:
    changed: list[str] = []
    unchanged: list[str] = []
    for relative, patcher in PATCHES:
        file = read_text_file(project_root / relative)
        patched = patcher(file.text)
        # Idempotence check before touching disk.
        if patcher(patched) != patched:
            raise PatchError(f"Patch non idempotente: {relative}")
        if patched == file.text:
            unchanged.append(relative)
        else:
            changed.append(relative)
            if apply:
                write_text_file(file, patched)
    return {
        "project_root": str(project_root),
        "mode": "apply" if apply else "check",
        "changed": changed,
        "unchanged": unchanged,
        "ready": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch semantica M52-M53, preserva modifiche non correlate.")
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT_DEFAULT)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        result = run(args.project_root, apply=args.apply)
    except PatchError as exc:
        result = {
            "project_root": str(args.project_root),
            "mode": "apply" if args.apply else "check",
            "ready": False,
            "error": str(exc),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
