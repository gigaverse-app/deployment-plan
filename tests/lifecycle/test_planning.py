from datetime import datetime, timezone

import pytest

from deployment_plan.manifest import load
from deployment_plan.models import Action, Inventory, Phase, Receipt, Status, Transition
from deployment_plan.planning import plan


def action(**changes):
    return Action.model_validate(
        {
            "id": "backfill-users",
            "instructions": "Run the backfill and verify the count.",
            "owner": "platform",
            "environments": ["staging", "production"],
            "phase": "after",
            "source_pr": 42,
            **changes,
        }
    )


def receipt(definition, operation="first", transition=Transition.COMPLETE, parents=(), environment="staging"):
    return Receipt(
        operation_id=operation,
        action_id=definition.id,
        revision=definition.revision,
        environment=environment,
        transition=transition,
        parents=parents,
        actor="operator",
        evidence="Verified count in deployment run 123",
        recorded_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_completion_survives_releases_and_environments_are_independent():
    definition = action()
    inventory = Inventory(actions=[definition])
    completed = receipt(definition)
    later = plan(inventory, "staging", [completed], base=inventory)
    assert later.errors == []
    assert later.pending == []
    assert later.items[0].carried
    production = plan(inventory, "production", [completed], base=inventory)
    assert [item.action.id for item in production.pending] == [definition.id]


@pytest.mark.parametrize(
    "change",
    [
        {"instructions": "Run a different command"},
        {"phase": Phase.BEFORE},
        {"environments": ("staging",)},
    ],
)
def test_operational_change_requires_fresh_completion(change):
    original = action()
    changed = action(**change)
    assert plan(Inventory(actions=[changed]), "staging", [receipt(original)]).pending


def test_provenance_edits_preserve_completion():
    original = action()
    changed = action(owner="new-owner", references=("https://example.com/runbook",))
    assert not plan(Inventory(actions=[changed]), "staging", [receipt(original)]).pending


def test_reopen_and_retirement_are_auditable_successors():
    definition = action()
    inventory = Inventory(actions=[definition])
    first = receipt(definition)
    reopen = receipt(definition, "second", Transition.REOPEN, ("first",))
    assert plan(inventory, "staging", [first, reopen]).pending
    retired = receipt(definition, "third", Transition.RETIRE, ("second",))
    resolved = plan(Inventory(), "staging", [first, reopen, retired], inventory)
    assert resolved.errors == []
    assert resolved.items[0].status == Status.RETIRED


def test_concurrent_writes_remain_visible_until_reconciled():
    definition = action()
    inventory = Inventory(actions=[definition])
    first = receipt(definition)
    racing = receipt(definition, "racing", Transition.REOPEN)
    conflict = plan(inventory, "staging", [first, racing])
    assert conflict.errors
    assert conflict.items[0].status == Status.CONFLICT
    reconciled = receipt(definition, "reconciled", parents=("first", "racing"))
    assert not plan(inventory, "staging", [first, racing, reconciled]).pending


def test_duplicate_operation_is_idempotent_and_conflicting_payload_is_invalid():
    definition = action()
    inventory = Inventory(actions=[definition])
    first = receipt(definition)
    assert plan(inventory, "staging", [first, first]).errors == []
    assert plan(inventory, "staging", [first, receipt(definition, transition=Transition.REOPEN)]).errors


@pytest.mark.parametrize(
    "events",
    [
        [("one", ("missing",))],
        [("one", ("one",))],
        [("one", ("two",)), ("two", ("one",))],
    ],
)
def test_incomplete_or_cyclic_history_cannot_report_success(events):
    definition = action()
    result = plan(
        Inventory(actions=[definition]), "staging", [receipt(definition, op, parents=parents) for op, parents in events]
    )
    assert result.errors
    assert result.pending


def test_removed_definition_is_visible_and_not_forgotten():
    definition = action()
    result = plan(Inventory(), "production", [], Inventory(actions=[definition]))
    assert result.errors
    assert result.pending[0].missing


def test_late_backfill_is_included_without_commit_range_membership(tmp_path):
    fragment = tmp_path / "late.yaml"
    fragment.write_text("""version: 1
actions:
  - id: late-backfill
    source_pr: 1
    instructions: Verify old migration
    owner: platform
    environments: [production]
    phase: during
""")
    inventory = load(tmp_path)
    assert inventory.errors == []
    assert [item.action.id for item in plan(inventory, "production", []).pending] == ["late-backfill"]


def test_invalid_manifest_keeps_valid_actions_but_cannot_be_successful(tmp_path):
    fragment = tmp_path / "actions.yaml"
    fragment.write_text("""version: 1
actions:
  - id: valid
    instructions: Verify migration
    owner: platform
    environments: [production]
    phase: before
  - id: broken
""")
    inventory = load(tmp_path)
    result = plan(inventory, "production", [])
    assert result.errors
    assert [item.action.id for item in result.pending] == ["valid"]
