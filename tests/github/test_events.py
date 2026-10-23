import copy
import json

import pytest

from deployment_plan.automation import execute
from deployment_plan.github import RECEIPT_MARKER, GitHub
from deployment_plan.models import Receipt
from deployment_plan.render import checkboxes

from .harness import GitHubHarness

MANIFEST = """version: 1
actions:
  - id: backfill
    source_pr: 42
    owner: platform
    environments: [staging, production]
    phase: after
    instructions: Run and verify the backfill.
"""


def promotion(number=100, base="staging"):
    return {
        "number": number,
        "pull_request": {
            "head": {"sha": "head", "repo": {"full_name": "example/service"}},
            "base": {"sha": "base", "ref": base},
        },
    }


def edit_event(comment, checked=True, sender="operator"):
    old = comment["body"]
    comment["body"] = old.replace("- [ ]", "- [x]", 1) if checked else old.replace("- [x]", "- [ ]", 1)
    comment["updated_at"] = "2026-10-01T12:00:00Z" if checked else "2026-10-01T12:01:00Z"
    return {
        "action": "edited",
        "issue": {"number": 100, "pull_request": {}},
        "comment": copy.deepcopy(comment),
        "changes": {"body": {"from": old}},
        "sender": {"login": sender},
    }


def test_promotion_checkbox_receipt_later_release_and_reopen(tmp_path):
    with GitHubHarness() as harness:
        harness.files = {"head": {"deployment/followups/task.yaml": MANIFEST}, "base": {}}
        event = promotion()
        harness.pulls[100] = event["pull_request"]
        api = GitHub(harness.repository, "test-token")
        environments = {"staging": "staging", "production": "production"}
        execute(api, event, "deployment/followups", environments, tmp_path / "initial")
        assert not checkboxes(harness.comments[100][0]["body"])["backfill"][1]
        edited = edit_event(harness.comments[100][0])
        execute(api, edited, "deployment/followups", environments, tmp_path / "edit")
        assert harness.comments[42][0]["body"].startswith(RECEIPT_MARKER)
        assert checkboxes(harness.comments[100][0]["body"])["backfill"][1]
        execute(api, edited, "deployment/followups", environments, tmp_path / "retry")
        assert len(harness.comments[42]) == 1
        execute(api, promotion(101), "deployment/followups", environments, tmp_path / "later")
        assert checkboxes(harness.comments[101][0]["body"])["backfill"][1]
        execute(api, promotion(102, "production"), "deployment/followups", environments, tmp_path / "prod")
        assert not checkboxes(harness.comments[102][0]["body"])["backfill"][1]
        reopened = edit_event(harness.comments[100][0], checked=False)
        execute(api, reopened, "deployment/followups", environments, tmp_path / "reopen")
        assert len(harness.comments[42]) == 2
        assert not checkboxes(harness.comments[100][0]["body"])["backfill"][1]
        api.close()


def test_non_promotion_comment_cannot_record_completion_even_with_valid_metadata(tmp_path):
    with GitHubHarness() as harness:
        harness.files = {"head": {"deployment/followups/task.yaml": MANIFEST}, "base": {}}
        event = promotion()
        api = GitHub(harness.repository, "test-token")
        environments = {"staging": "staging"}
        execute(api, event, "deployment/followups", environments, tmp_path / "initial")
        harness.pulls[100] = promotion(base="main")["pull_request"]
        edited = edit_event(harness.comments[100][0])
        with pytest.raises(ValueError, match="promotion branch"):
            execute(api, edited, "deployment/followups", environments, tmp_path / "edit")
        assert not harness.comments.get(42)
        api.close()


def test_unknown_comment_author_cannot_deny_history_reads():
    with GitHubHarness() as harness:
        api = GitHub(harness.repository, "test-token")
        assert not api.can_write("unknown-visitor")
        api.close()


def test_feature_branch_predating_adoption_does_not_delete_new_main_actions(tmp_path):
    with GitHubHarness() as harness:
        harness.files = {"head": {}, "base": {"deployment/followups/task.yaml": MANIFEST}, "common": {}}
        harness.merge_base = "common"
        api = GitHub(harness.repository, "test-token")
        execute(api, promotion(base="main"), "deployment/followups", {"staging": "staging"}, tmp_path)
        assert "No deployment action definitions changed" in harness.comments[100][0]["body"]
        api.close()


def test_read_only_pull_request_validation_never_writes_comments(tmp_path):
    with GitHubHarness() as harness:
        harness.files = {"head": {"deployment/followups/task.yaml": MANIFEST}, "base": {}}
        api = GitHub(harness.repository, "test-token")
        execute(api, promotion(base="main"), "deployment/followups", {"staging": "staging"}, tmp_path, publish=False)
        assert harness.comments == {}
        api.close()


@pytest.mark.parametrize("problem", ["visitor", "instructions", "stale", "revision"])
def test_invalid_checkbox_edits_cannot_create_receipts(tmp_path, problem):
    with GitHubHarness() as harness:
        harness.files = {"head": {"deployment/followups/task.yaml": MANIFEST}, "base": {}}
        event = promotion()
        harness.pulls[100] = event["pull_request"]
        api = GitHub(harness.repository, "test-token")
        environments = {"staging": "staging"}
        execute(api, event, "deployment/followups", environments, tmp_path / "initial")
        edited = edit_event(harness.comments[100][0], sender="visitor" if problem == "visitor" else "operator")
        if problem == "instructions":
            edited["comment"]["body"] = edited["comment"]["body"].replace("Run and verify", "Skip")
            harness.comments[100][0]["body"] = edited["comment"]["body"]
        elif problem == "stale":
            harness.comments[100][0]["body"] += "Newer edit"
        elif problem == "revision":
            harness.files["head"]["deployment/followups/task.yaml"] = MANIFEST.replace(
                "Run and verify", "Run a different command and verify"
            )
        with pytest.raises(ValueError):
            execute(api, edited, "deployment/followups", environments, tmp_path / "edit")
        assert not harness.comments.get(42)
        api.close()


def test_concurrent_receipt_during_checkbox_write_fails_with_visible_conflict(tmp_path):
    with GitHubHarness() as harness:
        harness.files = {"head": {"deployment/followups/task.yaml": MANIFEST}, "base": {}}
        event = promotion()
        harness.pulls[100] = event["pull_request"]
        api = GitHub(harness.repository, "test-token")
        environments = {"staging": "staging"}
        execute(api, event, "deployment/followups", environments, tmp_path / "initial")
        edited = edit_event(harness.comments[100][0])

        def concurrent_writer(request):
            response = harness.respond(request)
            if request.method == "POST" and request.url.path.endswith("/issues/42/comments"):
                receipt = Receipt.model_validate_json(json.loads(request.content)["body"].split("\n", 1)[1])
                other = receipt.model_copy(
                    update={"operation_id": "other-operator", "evidence": "Concurrent independent verification"}
                )
                rival = copy.deepcopy(harness.comments[42][-1])
                rival["id"] = 999
                rival["body"] = RECEIPT_MARKER + "\n" + other.model_dump_json()
                harness.comments[42].append(rival)
            return response

        harness.router.route().mock(side_effect=concurrent_writer)
        with pytest.raises(ValueError, match="conflicting"):
            execute(api, edited, "deployment/followups", environments, tmp_path / "edit")
        assert "conflict" in harness.comments[100][0]["body"]
        assert len(harness.comments[42]) == 2
        api.close()
