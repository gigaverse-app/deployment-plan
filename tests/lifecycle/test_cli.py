import json
import subprocess
import sys

FRAGMENT = """version: 1
actions:
  - id: backfill
    instructions: Run the backfill and verify 100 records.
    owner: platform
    source_pr: 42
    environments: [staging, production]
    phase: after
"""


def invoke(directory, *arguments, success=True):
    result = subprocess.run(
        [sys.executable, "-m", "deployment_plan", *arguments], cwd=directory, capture_output=True, text=True
    )
    assert (result.returncode == 0) == success, result.stdout + result.stderr
    return result


def test_operator_journey_runs_outside_checkout_and_persists_across_processes(tmp_path):
    fragment = tmp_path / "actions.yaml"
    fragment.write_text(FRAGMENT)
    common = ["--manifest", str(fragment)]
    invoke(tmp_path, "validate", *common)
    before = json.loads(invoke(tmp_path, "plan", *common, "--environment", "staging", "--format", "json").stdout)
    assert before["items"][0]["status"] == "pending"
    record = [
        "record",
        *common,
        "--environment",
        "staging",
        "--id",
        "backfill",
        "--transition",
        "complete",
        "--actor",
        "operator",
        "--evidence",
        "Verified 100 records",
        "--operation-id",
        "run-123",
    ]
    first = json.loads(invoke(tmp_path, *record).stdout)
    assert json.loads(invoke(tmp_path, *record).stdout) == first
    after = json.loads(
        invoke(
            tmp_path, "plan", *common, "--base-manifest", str(fragment), "--environment", "staging", "--format", "json"
        ).stdout
    )
    assert after["items"][0]["status"] == "complete"
    assert after["items"][0]["carried"]
    production = json.loads(invoke(tmp_path, "plan", *common, "--environment", "production", "--format", "json").stdout)
    assert production["items"][0]["status"] == "pending"
    invoke(
        tmp_path,
        "record",
        *common,
        "--environment",
        "staging",
        "--id",
        "backfill",
        "--transition",
        "reopen",
        "--actor",
        "operator",
        "--evidence",
        "Count was from wrong database",
        "--operation-id",
        "recheck",
    )
    reopened = json.loads(invoke(tmp_path, "plan", *common, "--environment", "staging", "--format", "json").stdout)
    assert reopened["items"][0]["status"] == "pending"


def test_invalid_input_returns_visible_diagnostic_and_nonzero(tmp_path):
    fragment = tmp_path / "broken.yaml"
    fragment.write_text("version: 999\nactions: []")
    result = invoke(tmp_path, "plan", "--manifest", str(fragment), "--environment", "production", success=False)
    assert "Plan needs attention" in result.stdout


def test_definition_change_cannot_reuse_an_operation_key(tmp_path):
    fragment = tmp_path / "actions.yaml"
    fragment.write_text(FRAGMENT)
    arguments = [
        "record",
        "--manifest",
        str(fragment),
        "--environment",
        "staging",
        "--id",
        "backfill",
        "--transition",
        "complete",
        "--actor",
        "operator",
        "--evidence",
        "Done",
        "--operation-id",
        "same",
    ]
    invoke(tmp_path, *arguments)
    fragment.write_text(FRAGMENT.replace("100 records", "200 records"))
    assert "different transition" in invoke(tmp_path, *arguments, success=False).stderr
