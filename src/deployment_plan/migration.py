"""Conservative import of explicitly checked legacy rows, with original evidence."""

import hashlib
from datetime import datetime

from deployment_plan.legacy import MARKER_PROMOTION, FollowupEntry, PromotionMatch, render_promotion_row
from deployment_plan.manifest import action_from_legacy
from deployment_plan.models import Receipt, Transition


def import_checked(
    entries: list[FollowupEntry],
    body: str,
    environment: str,
    evidence_url: str,
    actor: str,
    existing: list[Receipt],
    recorded_at: datetime,
) -> list[Receipt]:
    if not body.startswith(MARKER_PROMOTION) or f"landing on `{environment}`" not in body:
        return []
    body = "\n" + body.replace("\r\n", "\n").replace("- [X] PR #", "- [x] PR #") + "\n"
    receipts = []
    for entry in entries:
        for item in entry.followups:
            action = action_from_legacy(entry, item)
            if environment not in action.environments:
                continue
            if any(
                (r.action_id, r.revision, r.environment) == (action.id, action.revision, environment) for r in existing
            ):
                continue
            checked = render_promotion_row(PromotionMatch(entry=entry, item=item)).replace("- [ ]", "- [x]", 1)
            if "\n" + checked + "\n" not in body:
                continue
            operation = (
                "legacy:"
                + hashlib.sha256(f"{evidence_url}:{action.id}:{action.revision}:{environment}".encode()).hexdigest()
            )
            receipts.append(
                Receipt(
                    operation_id=operation,
                    action_id=action.id,
                    revision=action.revision,
                    environment=environment,
                    transition=Transition.COMPLETE,
                    actor=actor,
                    recorded_at=recorded_at,
                    evidence=f"Imported exact checked legacy row from {evidence_url}; original checkbox editor is unknown.",
                )
            )
    return receipts
