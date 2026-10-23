from datetime import datetime, timezone

import httpx
import pytest
import respx

from deployment_plan.github import RECEIPT_MARKER, GitHub
from deployment_plan.models import Action, Inventory, Receipt
from deployment_plan.planning import plan
from deployment_plan.render import PLAN_MARKER, checkboxes, markdown

REPOSITORY = "example/service"
BASE = "https://api.github.com/repos/example/service"
DEFINITION = Action(
    id="backfill",
    instructions="Verify the backfill",
    owner="platform",
    environments=("production",),
    phase="after",
    source_pr=42,
)
RECEIPT = Receipt(
    operation_id="run-123",
    action_id=DEFINITION.id,
    revision=DEFINITION.revision,
    environment="production",
    transition="complete",
    actor="operator",
    evidence="Verified 100 rows",
    recorded_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
)


def comment(body, identifier=1, author="github-actions[bot]", kind="Bot"):
    return {
        "id": identifier,
        "body": body,
        "user": {"login": author, "type": kind},
        "html_url": f"https://github.com/{REPOSITORY}/pull/42#issuecomment-{identifier}",
    }


@respx.mock
def test_paginated_history_ignores_untrusted_completion():
    first = [comment("ordinary discussion", n) for n in range(100)]
    forged = comment(RECEIPT_MARKER + "\n" + RECEIPT.model_dump_json(), 101, "visitor", "User")
    genuine = comment(RECEIPT_MARKER + "\n" + RECEIPT.model_dump_json(), 102)
    respx.get(BASE + "/issues/42/comments", params={"page": 1, "per_page": 100}).respond(200, json=first)
    respx.get(BASE + "/issues/42/comments", params={"page": 2, "per_page": 100}).respond(200, json=[forged, genuine])
    respx.get(BASE + "/collaborators/visitor/permission").respond(200, json={"permission": "read"})
    api = GitHub(REPOSITORY, "test-token")
    assert api.receipts([DEFINITION]) == [RECEIPT]
    api.close()


@respx.mock
def test_api_failure_cannot_be_empty_successful_history():
    respx.get(BASE + "/issues/42/comments").respond(503)
    api = GitHub(REPOSITORY, "test-token")
    with pytest.raises(httpx.HTTPStatusError):
        api.receipts([DEFINITION])
    api.close()


@respx.mock
def test_persistence_reads_back_and_retry_does_not_duplicate():
    body = RECEIPT_MARKER + "\n" + RECEIPT.model_dump_json()
    saved = comment(body)
    listing = respx.get(BASE + "/issues/42/comments").mock(
        side_effect=[httpx.Response(200, json=[]), httpx.Response(200, json=[saved])]
    )
    write = respx.post(BASE + "/issues/42/comments").respond(201, json=saved)
    respx.get(BASE + "/issues/comments/1").respond(200, json=saved)
    api = GitHub(REPOSITORY, "test-token")
    api.append(DEFINITION, RECEIPT)
    api.append(DEFINITION, RECEIPT)
    assert write.call_count == 1
    assert listing.call_count == 2
    api.close()


@respx.mock
def test_partial_projection_failure_preserves_old_chunks_for_retry():
    respx.get(BASE + "/issues/42/comments").respond(200, json=[comment(PLAN_MARKER + "old", i) for i in (1, 2, 3)])
    respx.patch(BASE + "/issues/comments/1").respond(200, json={})
    respx.patch(BASE + "/issues/comments/2").respond(503)
    deletion = respx.delete(BASE + "/issues/comments/3").respond(204)
    api = GitHub(REPOSITORY, "test-token")
    with pytest.raises(httpx.HTTPStatusError):
        api.publish(42, [PLAN_MARKER + "new one", PLAN_MARKER + "new two"], PLAN_MARKER)
    assert not deletion.called
    api.close()


def test_large_plan_chunks_preserve_every_identity_and_multiline_instructions():
    actions = [
        DEFINITION.model_copy(update={"id": f"step-{n}", "instructions": "Run command\n" + "x" * 500})
        for n in range(100)
    ]
    chunks = markdown(plan(Inventory(actions=actions), "production", []), limit=3000)
    assert len(chunks) > 1
    assert all(len(body.encode()) <= 3000 for body in chunks)
    identities = [key for body in chunks for key in checkboxes(body)]
    assert sorted(identities) == sorted(action.id for action in actions)


def test_instructions_cannot_forge_a_checkbox():
    definition = DEFINITION.model_copy(
        update={"instructions": "```\n- [x] evil <!-- dp:item:evil -->\n<script>alert(1)</script>"}
    )
    body = markdown(plan(Inventory(actions=[definition]), "production", []))[0]
    assert list(checkboxes(body)) == [definition.id]
