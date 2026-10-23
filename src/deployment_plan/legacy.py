#!/usr/bin/env python3
# gv:test-dependency: deployment/followups/pending.yaml
"""Compatibility API for the original deployment followup ledger and comments."""

import argparse
import datetime
import re
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

from deployment_plan.git import pull_request_numbers

MARKER_REVIEW = "<!-- deployment-followups-review -->"
MARKER_PROMOTION = "<!-- deployment-followups-promotion -->"
LINEAR_REF_RE = re.compile(r"^(?:https://linear\.app/[\w-]+/issue/)?([A-Z][A-Z0-9]*-\d+)(?:/[A-Za-z0-9._-]*)?/?$")


def _normalize_linear(v: str) -> str:
    match = LINEAR_REF_RE.match(v.strip())
    if match is None:
        raise ValueError(
            "linear must be a Linear issue URL "
            "(https://linear.app/<workspace>/issue/ABC-123/...) or a bare id (ABC-123)"
        )
    return (
        v.strip().rstrip("/").split("/issue/")[0] + "/issue/" + match.group(1)
        if v.strip().startswith("https://")
        else match.group(1)
    )


class Environment(str, Enum):
    STAGING = "staging"
    PRODUCTION = "production"
    BOTH = "both"

    def matches(self, target: str) -> bool:
        return self is Environment.BOTH or self.value == target


class Phase(str, Enum):
    BEFORE_DEPLOY = "before-deploy"
    DURING_DEPLOY = "during-deploy"
    AFTER_DEPLOY = "after-deploy"


class FollowupItem(BaseModel):
    """One manual step within a PR's deployment-followups entry."""

    id: str
    environment: Environment
    phase: Phase
    action: str


class FollowupEntry(BaseModel):
    """One PR's deployment followups in pending.yaml."""

    pr: int
    linear: str
    owner: str
    date: datetime.date
    followups: list[FollowupItem] = Field(min_length=1)

    @field_validator("linear")
    @classmethod
    def normalize_linear(cls, v: str) -> str:
        return _normalize_linear(v)

    @property
    def ticket_id(self) -> str:
        return self.linear.rsplit("/", 1)[-1]


class PromotionMatch(BaseModel):
    entry: FollowupEntry
    item: FollowupItem


class InvalidEntry(BaseModel):
    """A pending.yaml item that failed `FollowupEntry` validation."""

    position: int  # 1-based, in file order
    # The item exactly as YAML parsed it — its shape is unknown precisely
    # because it failed validation. Kept so the review surface can match it
    # against the base file by content.
    raw: Any
    issues: str

    @property
    def message(self) -> str:
        return f"entry #{self.position}: {self.issues}"

    @property
    def pr(self) -> int | None:
        """The item's PR number when it is one; anything else (a string, a bool, markdown) is never rendered."""
        pr = self.raw.get("pr") if isinstance(self.raw, dict) else None
        return pr if isinstance(pr, int) and not isinstance(pr, bool) else None

    @property
    def label(self) -> str:
        return f"entry #{self.position}" + (f" (PR #{self.pr})" if self.pr is not None else "")

    def content_key(self) -> str:
        # PyYAML's sorted dump is canonical for string-keyed items, dates
        # included. It doesn't crash on mixed-type keys, but then falls back
        # to insertion order, so reordering such an item re-echoes it.
        return yaml.safe_dump(self.raw, sort_keys=True)


class LoadedFollowups(BaseModel):
    """Everything read from one pending.yaml; also the shape of a PR's diff of it."""

    entries: list[FollowupEntry] = []
    invalid: list[InvalidEntry] = []
    file_errors: list[str] = []  # the file as a whole couldn't be read as a list of entries

    @property
    def errors(self) -> list[str]:
        return self.file_errors + [entry.message for entry in self.invalid]

    @property
    def is_empty(self) -> bool:
        return not (self.entries or self.invalid or self.file_errors)


def load_followups(path: Path) -> LoadedFollowups:
    """Load pending.yaml, keeping items that fail validation alongside the valid entries."""
    if not path.exists():
        return LoadedFollowups(file_errors=[f"followups file not found: {path}"])
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    # ValueError: PyYAML constructs some scalars while parsing (an impossible
    # date, a bad `!!int`), and UnicodeDecodeError is one too. Every caller —
    # including the OpenAPI ACK gate — must get a report, never a crash.
    except (yaml.YAMLError, ValueError) as exc:
        return LoadedFollowups(file_errors=[f"followups file is not valid YAML: {exc}"])
    if raw is None:
        return LoadedFollowups()
    if not isinstance(raw, list):
        return LoadedFollowups(file_errors=["followups file must be a YAML list of entries"])
    loaded = LoadedFollowups()
    for i, item in enumerate(raw):
        try:
            loaded.entries.append(FollowupEntry.model_validate(item))
        except ValidationError as exc:
            issues = "; ".join(_format_validation_issue(err["loc"], err["msg"]) for err in exc.errors())
            loaded.invalid.append(InvalidEntry(position=i + 1, raw=item, issues=issues))
    return loaded


def _format_validation_issue(loc: tuple[int | str, ...], msg: str) -> str:
    location = ".".join(str(part) for part in loc)
    return f"{location}: {msg}" if location else msg


def _added_or_changed[T](base: list[T], head: list[T], key: Callable[[T], str]) -> list[T]:
    """
    Head items with no identical base item, matched by content (`key`) — so
    position and PR number don't matter. The ledger may hold several entries
    for one PR, so base is a multiset: each head item consumes one identical
    base item, and only the unmatched ones are reported. Removed items
    (present in base, gone in head) aren't reported; there's nothing to echo
    once they're gone."""
    unmatched_base = Counter(key(item) for item in base)
    changed: list[T] = []
    for item in head:
        item_key = key(item)
        if unmatched_base[item_key]:
            unmatched_base[item_key] -= 1
        else:
            changed.append(item)
    return changed


def changed_entries(base_entries: list[FollowupEntry], head_entries: list[FollowupEntry]) -> list[FollowupEntry]:
    """Valid entries this PR's diff added or changed, regardless of which PR number they reference."""
    # Keyed by canonical JSON because FollowupEntry holds a list and so isn't
    # hashable; the JSON of a validated entry is equal exactly when the models are.
    return _added_or_changed(base_entries, head_entries, key=FollowupEntry.model_dump_json)


def changed_followups(base: LoadedFollowups, head: LoadedFollowups) -> LoadedFollowups:
    """
    What this PR's diff added or changed in pending.yaml. Invalid items are
    matched by raw content exactly like valid entries, so a broken entry
    already on the base branch isn't echoed on every PR that edits the
    ledger. A file-level error is reported only when the base file read
    cleanly: then this PR is what broke it."""
    return LoadedFollowups(
        entries=changed_entries(base.entries, head.entries),
        invalid=_added_or_changed(base.invalid, head.invalid, key=InvalidEntry.content_key),
        file_errors=[] if base.file_errors else head.file_errors,
    )


def matches_for_promotion(entries: list[FollowupEntry], pr_numbers: set[int], environment: str) -> list[PromotionMatch]:
    return [
        PromotionMatch(entry=entry, item=item)
        for entry in entries
        if entry.pr in pr_numbers
        for item in entry.followups
        if item.environment.matches(environment)
    ]


def invalid_for_promotion(invalid: list[InvalidEntry], pr_numbers: set[int]) -> list[InvalidEntry]:
    """
    Invalid entries that may belong to this promotion: their `pr` is in the
    range, or unreadable (it could be any PR). Checked at promotion time
    because review time can't see every way an entry becomes invalid — a
    schema change breaks it identically in base and head, so it cancels out
    of the review diff."""
    return [entry for entry in invalid if entry.pr is None or entry.pr in pr_numbers]


def _code_span(text: str) -> str:
    """One-line inline code: whitespace collapsed, delimited by more backticks than any run inside."""
    flat = " ".join(text.split())
    longest_run = max((len(run) for run in re.findall("`+", flat)), default=0)
    fence = "`" * (longest_run + 1)
    return f"{fence} {flat} {fence}"


def _render_validation_warning(
    file_errors: Sequence[str], invalid: Sequence[InvalidEntry], dropped_from: str
) -> list[str]:
    """
    A GitHub warning blockquote listing what failed validation. Every ledger-
    derived string goes through `_code_span` and every line starts with `> `,
    so nothing from the ledger (a multi-line YAML error, HTML-like `<...>`,
    markdown in a malformed field) can escape the block — an escaped `- [x]`
    would break the workflows' checkbox comparisons."""
    if not (file_errors or invalid):
        return []
    lines = ["> [!WARNING]", f"> These fail validation, so they are dropped from {dropped_from} until fixed:"]
    lines.extend(f"> - {_code_span(error)}" for error in file_errors)
    lines.extend(f"> - {entry.label}: {_code_span(entry.issues)}" for entry in invalid)
    lines.append("")
    return lines


def render_review_comment(changed: LoadedFollowups) -> str:
    lines = [MARKER_REVIEW, "**Deployment followups touched by this PR:**", ""]
    for entry in changed.entries:
        lines.append(f"PR #{entry.pr} ([{entry.ticket_id}]({entry.linear})):")
        for item in entry.followups:
            lines.append(f"- `{item.id}` — **{item.environment.value}**, {item.phase.value}: {item.action.strip()}")
        lines.append("")
    lines.extend(
        _render_validation_warning(
            changed.file_errors, changed.invalid, dropped_from="this comment and from every promotion checklist"
        )
    )
    lines.append("- [ ] Reviewer: these followups are correctly scoped (environments, phase, and nothing missing)")
    lines.append("")
    lines.append(
        "Tracked in `deployment/followups/pending.yaml`. Surfaces again as a "
        "checklist when the referenced PR's commits land on staging/production."
    )
    return "\n".join(lines).rstrip() + "\n"


def render_promotion_row(match: PromotionMatch) -> str:
    return (
        f"- [ ] PR #{match.entry.pr} (`{match.item.id}`, {match.item.phase.value}) — "
        f"{match.item.action.strip()} ([{match.entry.ticket_id}]({match.entry.linear}))"
    )


def render_promotion_checklist(
    matches: list[PromotionMatch],
    environment: str,
    *,
    file_errors: Sequence[str] = (),
    invalid: Sequence[InvalidEntry] = (),
) -> str:
    if not (matches or file_errors or invalid):
        return ""
    lines = [
        MARKER_PROMOTION,
        f"### Deployment followups landing on `{environment}`",
        "",
    ]
    for m in matches:
        lines.append(render_promotion_row(m))
    if matches:
        lines.append("")
    lines.extend(_render_validation_warning(file_errors, invalid, dropped_from="this checklist"))
    lines.append(
        "Check each box off once its runbook step has actually run — this comment "
        "is the one place that record lives (see docs/deployment-followups.md)."
    )
    return "\n".join(lines).rstrip() + "\n"


def preserve_checked_promotion_items(existing: str, rendered: str) -> str:
    """
    Carry ACKs forward only for byte-equivalent checklist rows.

    ``existing`` may contain several legacy sticky bodies concatenated
    together. This lets the workflow preserve an ACK made on any duplicate
    before consolidating them into one canonical comment.
    """
    checked_rows = {
        re.sub(r"^- \[[xX]\]", "- [ ]", line)
        for line in existing.replace("\r\n", "\n").splitlines()
        if re.match(r"^- \[[xX]\] PR #", line)
    }
    merged_lines = []
    for line in rendered.replace("\r\n", "\n").splitlines():
        if line in checked_rows:
            line = line.replace("- [ ]", "- [x]", 1)
        merged_lines.append(line)
    return "\n".join(merged_lines).rstrip() + "\n"


def cmd_review(args: argparse.Namespace) -> int:
    head = load_followups(args.pending)
    for err in head.errors:
        print(f"deployment-followups: {err}", file=sys.stderr)
    base = load_followups(args.pending_base)
    for err in base.errors:
        print(f"deployment-followups: (base) {err}", file=sys.stderr)
    changed = changed_followups(base, head)
    if changed.is_empty:
        args.comment_out.write_text("")
        print("deployment-followups: no entries changed in this PR's diff.")
        return 0
    # Still exit 0 when `changed` holds invalid entries: the surface is advisory.
    args.comment_out.write_text(render_review_comment(changed))
    print(
        f"deployment-followups: rendered sticky comment for {len(changed.entries)} entry/entries "
        f"and {len(changed.errors)} validation error(s)."
    )
    return 0


def cmd_promote(args: argparse.Namespace) -> int:
    loaded = load_followups(args.pending)
    for err in loaded.errors:
        print(f"deployment-followups: {err}", file=sys.stderr)
    pr_numbers = pull_request_numbers(args.base_sha, args.head_sha)
    matches = matches_for_promotion(loaded.entries, pr_numbers, args.environment)
    comment = render_promotion_checklist(
        matches,
        args.environment,
        file_errors=loaded.file_errors,
        invalid=invalid_for_promotion(loaded.invalid, pr_numbers),
    )
    args.comment_out.write_text(comment)
    print(
        f"deployment-followups: {len(matches)} followup(s) across "
        f"{len(pr_numbers)} PR(s) landing on {args.environment}."
    )
    return 0


def cmd_merge_promotion(args: argparse.Namespace) -> int:
    args.comment_out.write_text(preserve_checked_promotion_items(args.existing.read_text(), args.rendered.read_text()))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    review = subparsers.add_parser(
        "review",
        help="Render the sticky PR comment for entries this PR's diff changed.",
    )
    review.add_argument("--pending", required=True, type=Path, help="head-ref version")
    review.add_argument("--pending-base", required=True, type=Path, help="base-ref version")
    review.add_argument("--comment-out", required=True, type=Path)
    review.set_defaults(func=cmd_review)

    promote = subparsers.add_parser("promote", help="Render the sticky promotion checklist for a commit range.")
    promote.add_argument("--pending", required=True, type=Path)
    promote.add_argument("--base-sha", required=True)
    promote.add_argument("--head-sha", required=True)
    promote.add_argument("--environment", required=True, choices=["staging", "production"])
    promote.add_argument("--comment-out", required=True, type=Path)
    promote.set_defaults(func=cmd_promote)

    merge_promotion = subparsers.add_parser(
        "merge-promotion",
        help="Preserve ACKs for unchanged rows while refreshing a sticky checklist.",
    )
    merge_promotion.add_argument("--existing", required=True, type=Path)
    merge_promotion.add_argument("--rendered", required=True, type=Path)
    merge_promotion.add_argument("--comment-out", required=True, type=Path)
    merge_promotion.set_defaults(func=cmd_merge_promotion)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
