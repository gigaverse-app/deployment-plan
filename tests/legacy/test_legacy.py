# gv:test-dependency: deployment/followups/pending.yaml
"""
Unit tests for the deployment-followups tracker (docs/deployment-followups.md).

Pure functions plus a couple of real-git-repo CLI tests for the promotion
scan. CI selects these tests through the script import and the ledger
declaration above: without the declaration a PR changing only the ledger would
run none of them.
"""

import datetime
import subprocess
from pathlib import Path

import pytest
import yaml

from deployment_plan import legacy as followups

pytestmark = pytest.mark.no_db

TODAY = datetime.date(2026, 7, 7)


def make_item(
    id: str = "sync-room-channel-grants",
    environment: str = "production",
    phase: str = "after-deploy",
    action: str = "Run `sync_room_channel_grants --verify`, then `--apply`, then re-verify.",
) -> "followups.FollowupItem":
    return followups.FollowupItem(id=id, environment=environment, phase=phase, action=action)


def make_entry(
    pr: int = 3920,
    linear: str = "https://linear.app/example/issue/BE-600",
    owner: str = "aviad",
    items: list | None = None,
) -> "followups.FollowupEntry":
    return followups.FollowupEntry(
        pr=pr,
        linear=linear,
        owner=owner,
        date=TODAY,
        followups=items if items is not None else [make_item()],
    )


def _make_git_repo(path: Path) -> Path:
    repo = path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    return repo


def _commit(repo: Path, message: str) -> str:
    (repo / "file.txt").write_text(message)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=repo, check=True)
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


# Environment matching


@pytest.mark.parametrize(
    "environment,target,expected",
    [
        ("staging", "staging", True),
        ("staging", "production", False),
        ("production", "production", True),
        ("production", "staging", False),
        ("both", "staging", True),
        ("both", "production", True),
    ],
)
def test_environment_matches(environment, target, expected):
    assert followups.Environment(environment).matches(target) is expected


# Model validation


def test_followup_entry_requires_at_least_one_followup():
    with pytest.raises(Exception):
        followups.FollowupEntry(pr=1, linear="BE-1", owner="aviad", date=TODAY, followups=[])


@pytest.mark.parametrize(
    "ref",
    [
        "https://linear.app/example/issue/BE-600",
        "https://linear.app/example/issue/BE-600/",
        "BE-600",
    ],
)
def test_linear_ref_accepted_shapes_normalize_to_canonical_url(ref):
    """INVARIANT: full URLs and bare ids both normalize to the canonical issue URL."""
    entry = make_entry(linear=ref)
    assert entry.ticket_id == "BE-600"
    if ref.startswith("https://"):
        assert entry.linear.startswith(ref.split("/issue/")[0])
    else:
        assert entry.linear == "BE-600"
    assert entry.ticket_id == "BE-600"


@pytest.mark.parametrize("ref", ["", "BE600", "be-600", "https://example.com/BE-600"])
def test_linear_ref_invalid_shapes_rejected(ref):
    with pytest.raises(Exception):
        make_entry(linear=ref)


@pytest.mark.parametrize("environment", ["prod", "STAGING", ""])
def test_invalid_environment_rejected(environment):
    with pytest.raises(Exception):
        make_item(environment=environment)


@pytest.mark.parametrize("phase", ["before", "AFTER_DEPLOY", ""])
def test_invalid_phase_rejected(phase):
    with pytest.raises(Exception):
        make_item(phase=phase)


# load_followups


def test_load_followups_valid_file(tmp_path):
    pending_file = tmp_path / "pending.yaml"
    pending_file.write_text(
        yaml.dump(
            [
                {
                    "pr": 3920,
                    "linear": "BE-600",
                    "owner": "aviad",
                    "date": "2026-07-07",
                    "followups": [
                        {
                            "id": "sync-room-channel-grants",
                            "environment": "production",
                            "phase": "after-deploy",
                            "action": "run the sync script",
                        }
                    ],
                }
            ]
        )
    )
    loaded = followups.load_followups(pending_file)
    assert loaded.errors == []
    assert len(loaded.entries) == 1
    assert loaded.entries[0].followups[0].id == "sync-room-channel-grants"


def test_load_followups_empty_list_file_is_valid_and_empty(tmp_path):
    """INVARIANT: the seeded empty file ([]) is valid and yields no entries."""
    pending_file = tmp_path / "pending.yaml"
    pending_file.write_text("# comment\n[]\n")
    assert followups.load_followups(pending_file) == followups.LoadedFollowups()


def test_load_followups_comments_only_file_is_valid_and_empty(tmp_path):
    pending_file = tmp_path / "pending.yaml"
    pending_file.write_text("# nothing pending yet\n")
    assert followups.load_followups(pending_file) == followups.LoadedFollowups()


def test_load_followups_missing_file_is_an_error(tmp_path):
    loaded = followups.load_followups(tmp_path / "nope.yaml")
    assert loaded.entries == []
    assert len(loaded.file_errors) == 1


def test_load_followups_invalid_yaml_is_an_error(tmp_path):
    pending_file = tmp_path / "pending.yaml"
    pending_file.write_text("{ not: valid: yaml: [")
    loaded = followups.load_followups(pending_file)
    assert loaded.entries == []
    assert "not valid YAML" in loaded.file_errors[0]


def test_load_followups_non_list_is_an_error(tmp_path):
    pending_file = tmp_path / "pending.yaml"
    pending_file.write_text("key: value\n")
    loaded = followups.load_followups(pending_file)
    assert loaded.entries == []
    assert "must be a YAML list" in loaded.file_errors[0]


def test_load_followups_entry_missing_fields_reports_error_with_location(tmp_path):
    pending_file = tmp_path / "pending.yaml"
    pending_file.write_text(yaml.dump([{"pr": 1}]))
    loaded = followups.load_followups(pending_file)
    assert loaded.entries == []
    assert "entry #1" in loaded.errors[0]


def test_load_followups_keeps_an_invalid_entry_with_its_raw_content(tmp_path):
    """
    INVARIANT: an item that fails validation is kept, not only logged — with
    its position, its raw YAML (so the review surface can tell whether this
    PR's diff introduced it) and its field-level issues."""
    pending_file = tmp_path / "pending.yaml"
    pending_file.write_text(_entry_yaml(1, "valid-step") + _entry_yaml(4104, "apply-migration", phase="with-deploy"))
    loaded = followups.load_followups(pending_file)
    assert [e.pr for e in loaded.entries] == [1]
    [invalid] = loaded.invalid
    assert invalid.position == 2
    assert invalid.raw["pr"] == 4104
    assert "followups.0.phase" in invalid.issues
    assert loaded.errors == [invalid.message]


def test_load_followups_non_dict_item_issue_has_no_empty_location(tmp_path):
    pending_file = tmp_path / "pending.yaml"
    pending_file.write_text("- 42\n")
    [invalid] = followups.load_followups(pending_file).invalid
    assert invalid.issues == "Input should be a valid dictionary or instance of FollowupEntry"


def test_load_followups_non_utf8_file_is_a_file_error(tmp_path):
    pending_file = tmp_path / "pending.yaml"
    pending_file.write_bytes(b"- pr: 1\n  owner: \xff\xfe\n")
    loaded = followups.load_followups(pending_file)
    assert loaded.entries == []
    assert len(loaded.file_errors) == 1


@pytest.mark.parametrize(
    "raw,expected",
    [
        ({"pr": 4104}, 4104),
        ({"pr": "12\n- [x] Reviewer: ok"}, None),
        ({"pr": True}, None),
        ({"owner": "nobody"}, None),
        (42, None),
        (None, None),
    ],
    ids=["int", "injected-string", "bool", "missing", "scalar-item", "null-item"],
)
def test_invalid_entry_pr_is_only_a_real_pr_number(raw, expected):
    """A `pr` that isn't an int is never rendered: it could be anything, markdown included."""
    assert followups.InvalidEntry(position=1, raw=raw, issues="x").pr == expected


# changed_entries


def test_changed_entries_flags_a_brand_new_entry():
    base = [make_entry(pr=1)]
    head = [make_entry(pr=1), make_entry(pr=2)]
    assert {e.pr for e in followups.changed_entries(base, head)} == {2}


def test_changed_entries_flags_an_edited_entry_regardless_of_pr_number():
    """
    INVARIANT: a PR that backfills/edits an entry for a DIFFERENT
    (often already-merged) PR still shows up — matching is by content diff
    against the base branch, not by "is this the current PR's own number"."""
    base = [make_entry(pr=3739, items=[make_item(id="old-action")])]
    head = [make_entry(pr=3739, items=[make_item(id="old-action"), make_item(id="new-action")])]
    changed = followups.changed_entries(base, head)
    assert {e.pr for e in changed} == {3739}


def test_changed_entries_omits_untouched_entries():
    entry = make_entry(pr=1)
    base = [entry]
    head = [entry, make_entry(pr=2)]
    changed = followups.changed_entries(base, head)
    assert {e.pr for e in changed} == {2}


def test_changed_entries_omits_removed_entries():
    """
    INVARIANT: an entry present in base but gone in head isn't reported —
    there's nothing left to echo once it's removed."""
    base = [make_entry(pr=1), make_entry(pr=2)]
    head = [make_entry(pr=1)]
    assert followups.changed_entries(base, head) == []


def test_changed_entries_ignores_untouched_entries_sharing_a_pr_number():
    """
    REGRESSION: the ledger may hold several entries for one PR (#4088 has
    two). Keying base by `pr` kept only the last one, so every PR editing the
    ledger was told it touched the first — only the appended entry changed."""
    first = make_entry(pr=4088, items=[make_item(id="create-flags")])
    second = make_entry(pr=4088, items=[make_item(id="alerting-deferred")])
    appended = make_entry(pr=5079, items=[make_item(id="new-step")])
    base = [first, second]
    head = [first, second, appended]
    assert followups.changed_entries(base, head) == [appended]


@pytest.mark.parametrize("edited_index", [0, 1])
def test_changed_entries_flags_only_the_edited_entry_sharing_a_pr_number(edited_index):
    base = [
        make_entry(pr=4088, items=[make_item(id="create-flags")]),
        make_entry(pr=4088, items=[make_item(id="alerting-deferred")]),
    ]
    edited = make_entry(pr=4088, items=[make_item(id="edited", action="Edited.")])
    head = list(base)
    head[edited_index] = edited
    assert followups.changed_entries(base, head) == [edited]


def test_changed_entries_ignores_reordered_entries_sharing_a_pr_number():
    first = make_entry(pr=4088, items=[make_item(id="create-flags")])
    second = make_entry(pr=4088, items=[make_item(id="alerting-deferred")])
    assert followups.changed_entries([first, second], [second, first]) == []


def test_changed_entries_flags_an_added_identical_duplicate():
    """
    Matches are consumed one-for-one: a second copy of an existing entry
    is still something this PR's diff added."""
    entry = make_entry(pr=1)
    assert followups.changed_entries([entry], [entry, entry]) == [entry]


def test_changed_entries_against_empty_base_flags_everything():
    head = [make_entry(pr=1), make_entry(pr=2)]
    assert {e.pr for e in followups.changed_entries([], head)} == {1, 2}


# changed_followups: invalid items


def make_invalid(pr: int = 4104, phase: str = "with-deploy", position: int = 1) -> "followups.InvalidEntry":
    raw = yaml.safe_load(_entry_yaml(pr, "apply-migration", phase=phase))[0]
    return followups.InvalidEntry(position=position, raw=raw, issues="followups.0.phase: bad phase")


def test_changed_followups_flags_an_invalid_entry_added_by_this_pr():
    broken = make_invalid()
    base = followups.LoadedFollowups()
    head = followups.LoadedFollowups(invalid=[broken])
    assert followups.changed_followups(base, head).invalid == [broken]


def test_changed_followups_ignores_a_pre_existing_invalid_entry_even_when_it_moved():
    """
    INVARIANT: a broken entry already on the base branch isn't echoed on every
    PR that edits the ledger — matched by content, so an entry inserted above
    it (shifting its position) doesn't make it read as new."""
    base = followups.LoadedFollowups(invalid=[make_invalid(position=27)])
    head = followups.LoadedFollowups(entries=[make_entry(pr=5090)], invalid=[make_invalid(position=28)])
    changed = followups.changed_followups(base, head)
    assert changed.invalid == []
    assert [e.pr for e in changed.entries] == [5090]


def test_changed_followups_flags_an_edit_that_leaves_an_entry_invalid():
    base = followups.LoadedFollowups(invalid=[make_invalid(phase="with-deploy")])
    edited = make_invalid(phase="during-deploy")
    head = followups.LoadedFollowups(invalid=[edited])
    assert followups.changed_followups(base, head).invalid == [edited]


def test_changed_followups_hides_head_file_errors_only_when_base_was_already_broken():
    broken = followups.LoadedFollowups(file_errors=["followups file is not valid YAML: boom"])
    assert followups.changed_followups(followups.LoadedFollowups(), broken).file_errors == broken.file_errors
    assert followups.changed_followups(broken, broken).file_errors == []


def test_changed_followups_flags_an_added_identical_invalid_duplicate():
    broken = make_invalid()
    base = followups.LoadedFollowups(invalid=[broken])
    head = followups.LoadedFollowups(invalid=[broken, broken])
    assert followups.changed_followups(base, head).invalid == [broken]


# matches_for_promotion


def test_matches_for_promotion_filters_by_pr_and_environment():
    entries = [
        make_entry(pr=1, items=[make_item(environment="staging")]),
        make_entry(pr=2, items=[make_item(environment="production")]),
        make_entry(pr=3, items=[make_item(environment="both")]),
    ]
    matches = followups.matches_for_promotion(entries, {1, 2, 3}, "production")
    assert {m.entry.pr for m in matches} == {2, 3}


def test_matches_for_promotion_excludes_prs_outside_the_range():
    entries = [make_entry(pr=1), make_entry(pr=2)]
    matches = followups.matches_for_promotion(entries, {1}, "production")
    assert {m.entry.pr for m in matches} == {1}


# Rendering


def test_render_review_comment_contains_marker_items_and_ack_checkbox():
    entry = make_entry(items=[make_item(id="flip-ld-flag", action="Flip the FOO flag on.")])
    comment = followups.render_review_comment(followups.LoadedFollowups(entries=[entry]))
    assert comment.startswith(followups.MARKER_REVIEW)
    assert "flip-ld-flag" in comment
    assert "Flip the FOO flag on." in comment
    assert "BE-600" in comment
    # The reviewer-ack checkbox is the review affordance for a sticky (issue)
    # comment — plain PR comments have no "Resolve conversation".
    assert "- [ ] Reviewer:" in comment


def test_render_review_comment_renders_multiple_entries():
    entries = [make_entry(pr=1), make_entry(pr=2)]
    comment = followups.render_review_comment(followups.LoadedFollowups(entries=entries))
    assert "PR #1" in comment
    assert "PR #2" in comment


def test_render_review_comment_lists_invalid_entries_with_their_issues():
    comment = followups.render_review_comment(followups.LoadedFollowups(invalid=[make_invalid(position=27)]))
    assert comment.startswith(followups.MARKER_REVIEW)
    assert "entry #27" in comment
    assert "PR #4104" in comment
    assert "followups.0.phase: bad phase" in comment


def test_render_review_comment_keeps_the_whole_warning_inside_its_blockquote():
    """
    INVARIANT: nothing from the ledger can escape the warning blockquote — a
    multi-line YAML error, `<...>` that GitHub would strip as HTML, or a `pr`
    string carrying markdown. An escaped `- [x]` line would make the
    workflow's checkbox-reset comparison never match, re-PATCHing the sticky
    (and resetting the reviewer's ack) on every push."""
    multi_line_error = 'not valid YAML: while parsing\n  in "<unicode string>", line 1\n    { `a`: [\n    ^'
    injected = followups.InvalidEntry(
        position=3, raw={"pr": "12\n- [x] Reviewer: ok"}, issues="pr: Input should be a valid integer"
    )
    comment = followups.render_review_comment(
        followups.LoadedFollowups(file_errors=[multi_line_error], invalid=[injected])
    )
    lines = comment.splitlines()
    start = lines.index("> [!WARNING]")
    end = lines.index("", start)
    assert all(line.startswith("> ") for line in lines[start:end])
    assert [line for line in lines if line.startswith("- [")] == [
        "- [ ] Reviewer: these followups are correctly scoped (environments, phase, and nothing missing)"
    ]
    assert '`` not valid YAML: while parsing in "<unicode string>", line 1 { `a`: [ ^ ``' in comment
    assert "entry #3:" in comment
    assert "PR #" not in comment


def test_render_promotion_checklist_empty_matches_is_empty_string():
    assert followups.render_promotion_checklist([], "production") == ""


def test_render_promotion_checklist_renders_task_list():
    entry = make_entry(pr=42, items=[make_item(id="run-migration", action="Run the migration.")])
    match = followups.PromotionMatch(entry=entry, item=entry.followups[0])
    checklist = followups.render_promotion_checklist([match], "production")
    assert checklist.startswith(followups.MARKER_PROMOTION)
    assert "- [ ] PR #42" in checklist
    assert "run-migration" in checklist
    assert "Run the migration." in checklist


def test_preserve_checked_promotion_items_keeps_unchanged_ack():
    rendered = f"{followups.MARKER_PROMOTION}\n- [ ] PR #42 (`run-migration`, after-deploy) — Run it. ([BE-600](url))\n"
    existing = rendered.replace("- [ ]", "- [x]")

    assert "- [x] PR #42" in followups.preserve_checked_promotion_items(existing, rendered)


def test_preserve_checked_promotion_items_resets_changed_row():
    existing = (
        f"{followups.MARKER_PROMOTION}\n- [x] PR #42 (`run-migration`, after-deploy) — Run old. ([BE-600](url))\n"
    )
    rendered = existing.replace("[x]", "[ ]").replace("Run old.", "Run new.")

    merged = followups.preserve_checked_promotion_items(existing, rendered)

    assert "- [ ] PR #42" in merged
    assert "Run new." in merged


def test_preserve_checked_promotion_items_reads_ack_from_any_legacy_duplicate():
    rendered = f"{followups.MARKER_PROMOTION}\n- [ ] PR #42 (`run-migration`, after-deploy) — Run it. ([BE-600](url))\n"
    existing = rendered + "\n" + rendered.replace("- [ ]", "- [X]")

    assert "- [x] PR #42" in followups.preserve_checked_promotion_items(existing, rendered)


# CLI: review


def _entry_yaml(
    pr: int,
    item_id: str,
    linear: str = "BE-600",
    action: str = "run the sync script",
    phase: str = "after-deploy",
) -> str:
    return (
        f"- pr: {pr}\n"
        f"  linear: {linear}\n"
        "  owner: aviad\n"
        "  date: 2026-07-07\n"
        "  followups:\n"
        f"    - id: {item_id}\n"
        "      environment: production\n"
        f"      phase: {phase}\n"
        f"      action: {action}\n"
    )


def _run_review(tmp_path: Path, base_yaml: str, head_yaml: str) -> str:
    """Run the `review` CLI on a base/head pair of pending.yaml bodies; return the rendered comment."""
    base_file = tmp_path / "base.yaml"
    base_file.write_text(f"# header comment\n\n{base_yaml}")
    head_file = tmp_path / "pending.yaml"
    head_file.write_text(f"# header comment\n\n{head_yaml}")
    comment_out = tmp_path / "comment.md"
    argv = ["review", "--pending", str(head_file), "--pending-base", str(base_file), "--comment-out", str(comment_out)]
    assert followups.main(argv) == 0
    return comment_out.read_text()


def test_cli_review_writes_comment_for_entry_added_by_this_pr(tmp_path):
    comment = _run_review(tmp_path, "[]\n", _entry_yaml(3920, "sync-room-channel-grants"))
    assert comment.startswith(followups.MARKER_REVIEW)
    assert "PR #3920" in comment
    assert "sync-room-channel-grants" in comment


def test_cli_review_echoes_an_entry_backfilled_for_a_different_pr(tmp_path):
    """
    INVARIANT: this PR's own number doesn't have to appear anywhere in the
    file for the echo to fire — adding/editing an entry for a different,
    already-merged PR is exactly the App Check backfill case (#3930 adding an
    entry for #3739)."""
    comment = _run_review(tmp_path, "[]\n", _entry_yaml(3739, "enable-app-check-enforce", linear="BE-516"))
    assert "PR #3739" in comment
    assert "enable-app-check-enforce" in comment


def test_cli_review_omits_entries_unchanged_from_base(tmp_path):
    unchanged = _entry_yaml(100, "unrelated", linear="BE-1")
    assert _run_review(tmp_path, unchanged, unchanged) == ""


def test_cli_review_omits_untouched_entries_sharing_a_pr_number(tmp_path):
    """
    REGRESSION (#5079): pending.yaml holds two entries for PR 4088; a PR that
    only appended its own entry was also shown #4088's first entry."""
    ledger = _entry_yaml(4088, "create-event-reminder-sender-flags") + _entry_yaml(
        4088, "reminder-sender-unavailable-alerting-deferred"
    )
    comment = _run_review(tmp_path, ledger, ledger + _entry_yaml(5079, "new-step"))
    assert "PR #5079" in comment
    assert "PR #4088" not in comment


def test_cli_review_writes_empty_file_when_nothing_changed(tmp_path):
    assert _run_review(tmp_path, "[]\n", "[]\n") == ""


def test_cli_review_surfaces_a_malformed_entry_added_by_this_pr(tmp_path):
    """
    REGRESSION: #4104's entry carried `phase: with-deploy`; the loader dropped
    it with a stderr line only, so the review comment never rendered and every
    promotion checklist silently omitted it. The review comment must name the
    broken entry and the offending field — and stay advisory (exit 0, which
    _run_review asserts)."""
    head = _entry_yaml(1, "valid-step") + _entry_yaml(4104, "apply-migration", phase="with-deploy")
    comment = _run_review(tmp_path, _entry_yaml(1, "valid-step"), head)
    assert comment.startswith(followups.MARKER_REVIEW)
    assert "entry #2 (PR #4104)" in comment
    assert "followups.0.phase" in comment
    assert "'before-deploy', 'during-deploy' or 'after-deploy'" in comment
    assert "PR #1 " not in comment


def test_cli_review_does_not_echo_a_pre_existing_malformed_entry(tmp_path):
    broken = _entry_yaml(4104, "apply-migration", phase="with-deploy")
    comment = _run_review(tmp_path, broken, _entry_yaml(5090, "new-step") + broken)
    assert "PR #5090" in comment
    assert "4104" not in comment


def test_cli_review_is_silent_when_only_a_pre_existing_malformed_entry_exists(tmp_path):
    broken = _entry_yaml(4104, "apply-migration", phase="with-deploy")
    assert _run_review(tmp_path, broken, broken) == ""


def test_cli_review_echoes_the_repaired_entry_once_fixed(tmp_path):
    broken = _entry_yaml(4104, "apply-migration", phase="with-deploy")
    fixed = _entry_yaml(4104, "apply-migration", phase="before-deploy")
    comment = _run_review(tmp_path, broken, fixed)
    assert "PR #4104" in comment
    assert "before-deploy" in comment
    assert "fail validation" not in comment


def test_cli_review_surfaces_a_file_this_pr_made_unparseable(tmp_path):
    comment = _run_review(tmp_path, _entry_yaml(1, "valid-step"), "{ not: valid: yaml: [")
    assert comment.startswith(followups.MARKER_REVIEW)
    assert "not valid YAML" in comment


def test_cli_review_reports_a_load_time_value_error_instead_of_crashing(tmp_path):
    """
    REGRESSION: PyYAML constructs dates while parsing, so an impossible date
    raised ValueError out of load_followups — the advisory job (and the
    OpenAPI ACK gate, which shares the loader) crashed with exit 1 and no
    comment. It must surface as a file error instead."""
    bad_date = _entry_yaml(4200, "new-step").replace("2026-07-07", "2026-02-30")
    comment = _run_review(tmp_path, _entry_yaml(1, "valid-step"), bad_date)
    # The datetime message wording varies by Python version; the invariant is
    # "exit 0 (asserted by _run_review) and the file error is on the comment".
    assert "followups file is not valid YAML:" in comment


def test_cli_review_hides_head_file_errors_when_base_was_already_broken(tmp_path):
    """A ledger already unreadable on the base branch isn't blamed on every PR."""
    assert _run_review(tmp_path, "{ broken: [", "{ still: broken: [") == ""


def test_cli_review_flags_a_valid_entry_this_pr_broke(tmp_path):
    comment = _run_review(
        tmp_path,
        _entry_yaml(4104, "apply-migration"),
        _entry_yaml(4104, "apply-migration", phase="with-deploy"),
    )
    assert "entry #1 (PR #4104)" in comment


# CLI: promote


def _run_promote(tmp_path: Path, monkeypatch, pending_yaml: str, prs_in_range: list[int], environment: str) -> str:
    """Run the `promote` CLI over a real git range holding one commit per PR; return the rendered comment."""
    repo = _make_git_repo(tmp_path)
    base_sha = _commit(repo, "initial commit")
    head_sha = base_sha
    for pr in prs_in_range:
        head_sha = _commit(repo, f"Some fix (#{pr})")
    monkeypatch.chdir(repo)
    pending_file = tmp_path / "pending.yaml"
    pending_file.write_text(pending_yaml)
    comment_out = tmp_path / "comment.md"
    argv = [
        "promote",
        "--pending",
        str(pending_file),
        "--base-sha",
        base_sha,
        "--head-sha",
        head_sha,
        "--environment",
        environment,
        "--comment-out",
        str(comment_out),
    ]
    assert followups.main(argv) == 0
    return comment_out.read_text()


def test_cli_promote_writes_checklist_scoped_to_prs_in_range(tmp_path, monkeypatch):
    pending = _entry_yaml(101, "sync-room-channel-grants") + _entry_yaml(999, "unrelated", linear="BE-601")
    body = _run_promote(tmp_path, monkeypatch, pending, [101, 102], "production")
    assert "PR #101" in body
    assert "PR #999" not in body


def test_cli_promote_writes_empty_comment_when_no_prs_match(tmp_path, monkeypatch):
    assert _run_promote(tmp_path, monkeypatch, "[]\n", [555], "staging") == ""


def test_cli_promote_warns_about_invalid_entries_that_may_belong_to_the_range(tmp_path, monkeypatch):
    """
    INVARIANT: an entry that fails validation never drops out of a promotion
    silently — however it became invalid, including a schema change that
    broke it identically on both sides of the review diff. It is listed when
    its `pr` is in the range, or unreadable (it could be any PR); an invalid
    entry for a PR outside the range is not."""
    pending = (
        _entry_yaml(101, "valid-step")
        + _entry_yaml(102, "in-range-broken", phase="with-deploy")
        + _entry_yaml(999, "out-of-range-broken", phase="with-deploy")
        + "- owner: nobody\n"
    )
    body = _run_promote(tmp_path, monkeypatch, pending, [101, 102], "production")
    assert "- [ ] PR #101" in body
    assert "entry #2 (PR #102)" in body
    assert "entry #4:" in body
    assert "999" not in body


def test_cli_promote_warns_when_the_ledger_is_unreadable(tmp_path, monkeypatch):
    body = _run_promote(tmp_path, monkeypatch, "{ not: valid: yaml: [", [101], "staging")
    assert body.startswith(followups.MARKER_PROMOTION)
    assert "not valid YAML" in body
