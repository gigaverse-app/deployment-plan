from datetime import datetime, timezone

from deployment_plan.legacy import FollowupEntry, PromotionMatch, render_promotion_checklist
from deployment_plan.migration import import_checked
from deployment_plan.models import Action, Receipt

ENTRY = FollowupEntry.model_validate(
    {
        "pr": 42,
        "linear": "https://linear.app/example/issue/OPS-1",
        "owner": "platform",
        "date": "2026-10-01",
        "followups": [
            {"id": "backfill", "environment": "both", "phase": "after-deploy", "action": "Run and verify the backfill."}
        ],
    }
)
ACTION = Action(
    id="pr-42/backfill",
    source_pr=42,
    owner="platform",
    environments=("staging", "production"),
    phase="after",
    instructions="Run and verify the backfill.",
    references=(ENTRY.linear,),
)


def test_import_requires_exact_checked_definition_and_records_evidence():
    body = render_promotion_checklist([PromotionMatch(entry=ENTRY, item=ENTRY.followups[0])], "production")
    assert not import_checked(
        [ENTRY],
        body,
        "production",
        "https://github.com/example/service/pull/100#issuecomment-1",
        "operator",
        [],
        datetime.now(timezone.utc),
    )
    receipts = import_checked(
        [ENTRY],
        body.replace("- [ ]", "- [x]"),
        "production",
        "https://github.com/example/service/pull/100#issuecomment-1",
        "operator",
        [],
        datetime.now(timezone.utc),
    )
    assert len(receipts) == 1
    assert receipts[0].environment == "production"
    assert receipts[0].action_id == ACTION.id
    assert receipts[0].revision == ACTION.revision
    assert "original checkbox editor is unknown" in receipts[0].evidence
    assert not import_checked(
        [ENTRY],
        body.replace("- [ ]", "- [x]").replace("verify", "skip"),
        "production",
        "https://github.com/example/service/pull/100#issuecomment-1",
        "operator",
        [],
        datetime.now(timezone.utc),
    )


def test_import_cannot_overwrite_a_later_reopening():
    existing = Receipt(
        operation_id="reopen",
        action_id=ACTION.id,
        revision=ACTION.revision,
        environment="production",
        transition="reopen",
        actor="operator",
        evidence="Recheck required",
        recorded_at=datetime.now(timezone.utc),
    )
    body = render_promotion_checklist([PromotionMatch(entry=ENTRY, item=ENTRY.followups[0])], "production").replace(
        "- [ ]", "- [x]"
    )
    assert not import_checked(
        [ENTRY],
        body,
        "production",
        "https://github.com/example/service/pull/100#issuecomment-1",
        "operator",
        [existing],
        datetime.now(timezone.utc),
    )
