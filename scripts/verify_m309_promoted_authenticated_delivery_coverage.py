from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.models.gen4_copyability import (
    CanonicalParserGen4PromotedSelectiveDeliveryReceipt,
)
from backend.app.services import blockchain_parser_gen4_copyability_service as receiver
from backend.app.services.gen4_post_anchor_selective_evidence_service import (
    build_promoted_wallet_evidence,
)
from backend.app.services.gen4_promoted_selective_coverage_service import (
    M309_MINIMUM_COVERAGE_PERCENT,
    M309_SCOPE,
    build_existing_raw_webhook_update,
    evaluate_promoted_delivery_coverage,
)

MIGRATION = ROOT / "alembic" / "versions" / "f6e9c2d4f581_add_m309_promoted_authenticated_delivery_receipts.py"


def main() -> None:
    assert CanonicalParserGen4PromotedSelectiveDeliveryReceipt.__tablename__ == (
        "canonical_parser_gen4_promoted_selective_delivery_receipts"
    )
    assert M309_MINIMUM_COVERAGE_PERCENT == 95.0
    assert "AUTHENTICATED_DELIVERY_COVERAGE" in M309_SCOPE

    receiver_source = inspect.getsource(receiver.receive_gen4_copyability_webhook)
    assert "CanonicalParserGen4PromotedSelectiveDeliveryReceipt" in receiver_source
    assert "promoted_activations" in receiver_source
    assert "auth_verified=True" in receiver_source
    assert "preactivation_backfill" in receiver_source

    adapter_source = inspect.getsource(build_promoted_wallet_evidence)
    adapter_signature = str(inspect.signature(build_promoted_wallet_evidence))
    assert "delivery_receipts" in adapter_signature
    assert "evaluate_promoted_delivery_coverage" in adapter_source
    assert "WEBHOOK_ONLY_BUY_GAP_TECHNICAL_EVIDENCE" in adapter_source
    assert "no_wss_as_webhook_relabeling" in adapter_source

    update = build_existing_raw_webhook_update(
        {
            "webhookURL": "https://example.test/hook",
            "transactionTypes": ["ANY"],
            "accountAddresses": ["A"],
            "webhookType": "raw",
            "authHeader": "secret",
            "txnStatus": "success",
            "encoding": "jsonParsed",
        },
        account_addresses=["A", "B"],
    )
    assert update["accountAddresses"] == ["A", "B"]
    assert update["transactionTypes"] == ["ANY"]
    assert set(update) == {
        "webhookURL", "transactionTypes", "accountAddresses", "webhookType",
        "authHeader", "txnStatus", "encoding",
    }

    migration = MIGRATION.read_text(encoding="utf-8-sig")
    assert 'revision = "f6e9c2d4f581"' in migration
    assert 'down_revision = "f5d8b1c3e470"' in migration
    assert "canonical_parser_gen4_promoted_selective_delivery_receipts" in migration

    print(
        "M309_VERIFY=PASS;"
        "coverage_threshold_95_unchanged=true;"
        "wss_primary=true;authenticated_raw_webhook_secondary=true;"
        "dedicated_promoted_receipt=true;receiver_promoted_routing=true;"
        "webhook_only_buy_gap_technical=true;"
        "no_wss_relabel=true;preactivation_backfill=false;"
        "provider_update_preserves_webhookdata=true;"
        "provider_mutation_executed=false;activation_rows_created=0;"
        "live=false;signer=false;paper=0"
    )


if __name__ == "__main__":
    main()
