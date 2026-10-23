from datetime import datetime

import pytest
from pydantic import ValidationError

from deployment_plan.cli import main
from deployment_plan.manifest import load
from deployment_plan.models import Action, Receipt
from deployment_plan.storage import LocalStore


@pytest.mark.parametrize(
    "content",
    [
        "{ invalid: [",
        "version: 2\nactions: []",
        "- pr: 42\n",
        "version: 1\nactions: [false]",
        "version: 1\nactions: []\nunknown: yes",
    ],
)
def test_invalid_manifests_fail_cli_with_diagnostics(tmp_path, capsys, content):
    manifest = tmp_path / "actions.yaml"
    manifest.write_text(content)
    assert main(["validate", "--manifest", str(manifest)]) == 1
    assert "error(s)" in capsys.readouterr().out
    assert load(manifest).errors


def test_missing_and_unreadable_manifests_are_errors(tmp_path):
    path = tmp_path / "missing.yaml"
    assert load(path).errors
    path.write_bytes(b"\xff")
    assert load(path).errors


@pytest.mark.parametrize(
    "changes",
    [
        {"instructions": " "},
        {"owner": " "},
        {"environments": ["prod", "prod"]},
        {"environments": ["a/b"]},
        {"source_pr": True},
    ],
)
def test_authoring_rejects_ambiguous_scope_and_empty_instructions(changes):
    with pytest.raises(ValidationError):
        Action.model_validate(
            {
                "id": "step",
                "instructions": "Run command",
                "owner": "platform",
                "environments": ["prod"],
                "phase": "after",
                **changes,
            }
        )


def test_receipts_require_evidence_and_timezone():
    values = {
        "operation_id": "run",
        "action_id": "step",
        "revision": "a" * 64,
        "environment": "prod",
        "transition": "complete",
        "actor": "operator",
        "evidence": "Verified",
        "recorded_at": "2026-10-01T00:00:00Z",
    }
    for changes in [{"evidence": " "}, {"actor": " "}, {"recorded_at": datetime(2026, 1, 1)}]:
        with pytest.raises(ValidationError):
            Receipt.model_validate({**values, **changes})


def test_local_store_is_durable_idempotent_and_never_overwrites(tmp_path):
    store = LocalStore(tmp_path / "state.sqlite3")
    assert store.read() == []
    receipt = Receipt(
        operation_id="run",
        action_id="step",
        revision="a" * 64,
        environment="prod",
        transition="complete",
        actor="operator",
        evidence="Verified",
        recorded_at="2026-10-01T00:00:00Z",
    )
    store.append(receipt)
    store.append(receipt)
    assert LocalStore(store.path).read() == [receipt]
    with pytest.raises(ValueError, match="different content"):
        store.append(receipt.model_copy(update={"evidence": "Different"}))
    assert store.read() == [receipt]


def test_cli_records_and_renders_current_local_state(tmp_path, capsys):
    manifest = tmp_path / "actions.yaml"
    manifest.write_text(
        "version: 1\nactions:\n  - id: step\n    instructions: Run command\n    owner: platform\n    environments: [prod]\n    phase: before\n"
    )
    common = ["--manifest", str(manifest), "--state", str(tmp_path / "state.sqlite3")]
    assert (
        main(
            [
                "record",
                *common,
                "--environment",
                "prod",
                "--id",
                "step",
                "--transition",
                "complete",
                "--operation-id",
                "run",
                "--evidence",
                "Verified",
                "--actor",
                "operator",
            ]
        )
        == 0
    )
    assert main(["plan", *common, "--environment", "prod", "--format", "json"]) == 0
    assert '"status": "complete"' in capsys.readouterr().out
    assert main(["review", *common, "--base-manifest", str(manifest)]) == 0
    assert "No deployment action definitions changed" in capsys.readouterr().out
