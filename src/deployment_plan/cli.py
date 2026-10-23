"""Command-line entry points for offline and GitHub-backed deployment plans."""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

from deployment_plan import legacy
from deployment_plan.github import Comment, GitHub, User
from deployment_plan.manifest import load
from deployment_plan.models import Action, Inventory, Receipt, Status, Transition
from deployment_plan.planning import plan, resolve
from deployment_plan.render import PLAN_MARKER, checkboxes, code, markdown
from deployment_plan.storage import LocalStore

REVIEW_MARKER = "<!-- deployment-plan:review:v1 -->"


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Carry deployment obligations from PRs through every release.")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("validate", "plan", "review", "record", "sync-checkbox"):
        command = commands.add_parser(name)
        command.add_argument("--manifest", type=Path, default=Path("deployment/followups"))
        if name != "validate":
            command.add_argument("--repo", help="GitHub owner/repository; otherwise use local state")
            command.add_argument("--state", type=Path, default=Path(".deployment-plan/receipts.sqlite3"))
        if name in {"review", "plan"}:
            command.add_argument("--base-manifest", type=Path)
            command.add_argument("--output", type=Path)
            command.add_argument("--publish-pr", type=int)
        if name in {"record", "plan"}:
            command.add_argument("--environment", required=True)
        if name == "plan":
            command.add_argument("--format", choices=["json", "markdown"], default="markdown")
        if name == "record":
            command.add_argument("--id", required=True)
            command.add_argument("--transition", choices=[item.value for item in Transition], required=True)
            command.add_argument("--evidence", required=True)
            command.add_argument(
                "--operation-id", required=True, help="Stable retry key, e.g. deployment run ID plus action"
            )
            command.add_argument(
                "--actor", help="Required for local history; verified against GitHub permissions online"
            )
            command.add_argument(
                "--reconcile", action="store_true", help="Explicitly supersede every conflicting frontier"
            )
        if name == "sync-checkbox":
            command.add_argument("--event", type=Path, required=True)
    compatibility = commands.add_parser("legacy", help="Original ledger and comment CLI compatibility")
    compatibility.add_argument("arguments", nargs=argparse.REMAINDER)
    return root


def github(args: argparse.Namespace) -> GitHub | None:
    if not args.repo:
        return None
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("GH_TOKEN or GITHUB_TOKEN is required with --repo")
    return GitHub(args.repo, token)


def read_receipts(args: argparse.Namespace, inventory: Inventory, api: GitHub | None) -> list[Receipt]:
    return api.receipts(inventory.actions) if api else LocalStore(args.state).read()


def persist(args: argparse.Namespace, action: Action, receipt: Receipt, api: GitHub | None) -> None:
    if api:
        api.append(action, receipt)
    else:
        LocalStore(args.state).append(receipt)


def record(args: argparse.Namespace, inventory: Inventory, api: GitHub | None) -> None:
    definition = next((action for action in inventory.actions if action.id == args.id), None)
    if definition is None:
        raise ValueError(f"unknown action: {args.id}")
    if args.environment not in definition.environments:
        raise ValueError(f"{args.id} does not target {args.environment}")
    actor = args.actor or (api.actor() if api else None)
    if not actor:
        raise ValueError("--actor is required for local receipts")
    if api and not api.can_write(actor):
        raise ValueError(f"{actor} does not have repository write permission")
    if api and not os.environ.get("GITHUB_ACTIONS") and actor != api.actor():
        raise ValueError("a human credential may only record its authenticated actor")
    receipts = read_receipts(args, inventory, api)
    previous = next((receipt for receipt in receipts if receipt.operation_id == args.operation_id), None)
    if previous:
        if (
            previous.action_id,
            previous.revision,
            previous.environment,
            previous.transition,
            previous.actor,
            previous.evidence,
        ) != (definition.id, definition.revision, args.environment, args.transition, actor, args.evidence.strip()):
            raise ValueError("operation ID was already used for a different transition")
        print(previous.model_dump_json())
        return
    current = resolve(definition, args.environment, receipts)
    if current.status == Status.CONFLICT and not args.reconcile:
        raise ValueError("history has conflicting transitions; inspect evidence, then use --reconcile")
    receipt = Receipt(
        operation_id=args.operation_id,
        action_id=definition.id,
        revision=definition.revision,
        environment=args.environment,
        transition=args.transition,
        parents=current.frontier,
        actor=actor,
        evidence=args.evidence,
        recorded_at=datetime.now(timezone.utc),
    )
    persist(args, definition, receipt, api)
    after = resolve(definition, args.environment, read_receipts(args, inventory, api))
    if after.status == Status.CONFLICT:
        raise ValueError("receipt saved, but a concurrent update conflicts; inspect and reconcile")
    print(receipt.model_dump_json())


def sync_checkbox(args: argparse.Namespace, inventory: Inventory, api: GitHub | None) -> None:
    if api is None:
        raise ValueError("sync-checkbox requires --repo")
    event = json.loads(args.event.read_text())
    if event.get("action") != "edited" or "pull_request" not in event.get("issue", {}):
        raise ValueError("expected a pull-request issue_comment edited event")
    comment = Comment.model_validate(event["comment"])
    sender = User.model_validate(event["sender"])
    if comment.user.login != "github-actions[bot]" or comment.user.type != "Bot":
        raise ValueError("only workflow-authored plan comments can record checkbox transitions")
    if not api.can_write(sender.login):
        raise ValueError("checkbox editor lacks repository write permission")
    saved = Comment.model_validate(api.request("GET", f"/repos/{api.repository}/issues/comments/{comment.id}"))
    if saved.body != comment.body:
        raise ValueError("a newer edit superseded this event; inspect the current checklist")
    before = checkboxes(event["changes"]["body"]["from"])
    after = checkboxes(comment.body)
    definitions = {action.id: action for action in inventory.actions}
    receipts = api.receipts(inventory.actions)
    for key, (metadata, checked) in after.items():
        if key not in before or before[key][1] == checked:
            continue
        if metadata != before[key][0]:
            raise ValueError("checkbox identity was edited; refresh the plan before completing it")
        definition = definitions.get(key)
        if (
            definition is None
            or metadata.revision != definition.revision
            or metadata.environment not in definition.environments
        ):
            raise ValueError(f"stale or unknown action: {key}; refresh the plan")
        operation = (
            "checkbox:" + hashlib.sha256(f"{comment.id}:{event['comment']['updated_at']}:{key}".encode()).hexdigest()
        )
        if any(receipt.operation_id == operation for receipt in receipts):
            continue
        current = resolve(definition, metadata.environment, receipts)
        if current.frontier != metadata.parents:
            raise ValueError(f"{key}: completion history changed; refresh the plan before editing")
        receipt = Receipt(
            operation_id=operation,
            action_id=key,
            revision=definition.revision,
            environment=metadata.environment,
            transition=Transition.COMPLETE if checked else Transition.REOPEN,
            parents=current.frontier,
            actor=sender.login,
            evidence=comment.html_url,
            recorded_at=event["comment"]["updated_at"],
        )
        api.append(definition, receipt)
        receipts.append(receipt)
    print("Checkbox changes recorded. Refresh the plan to show current receipt identities.")


def emit(args: argparse.Namespace, text: str) -> None:
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="" if text.endswith("\n") else "\n")


def run(args: argparse.Namespace, api: GitHub | None) -> int:
    inventory = load(args.manifest)
    if args.command == "validate":
        for error in inventory.errors:
            print(error, file=sys.stderr)
        print(f"{len(inventory.actions)} action(s), {len(inventory.errors)} error(s)")
        return int(bool(inventory.errors))
    base = load(args.base_manifest) if getattr(args, "base_manifest", None) else Inventory()
    if args.command == "review":
        previous = {action.id: action for action in base.actions}
        changed = [action for action in inventory.actions if previous.get(action.id) != action]
        removed = set(previous) - {action.id for action in inventory.actions}
        errors = [
            *inventory.errors,
            *base.errors,
            *(f"{key}: keep the definition and explicitly retire it" for key in sorted(removed)),
        ]
        blocks = [
            f"### {action.id}\n\n"
            + code(
                f"{action.phase.value}: {', '.join(action.environments)}\nOwner: {action.owner}\n\n{action.instructions}"
            )
            for action in changed
        ]
        body = (
            REVIEW_MARKER
            + "\n## Deployment actions changed by this PR\n\n"
            + "\n\n".join(blocks + [code(error) for error in errors])
        )
        if not changed and not errors:
            body += "No deployment action definitions changed."
        body += "\n\nReview the scope, owner, instructions and source PR before merging.\n"
        emit(args, body)
        if args.publish_pr:
            if api is None:
                raise ValueError("--publish-pr requires --repo")
            if len(body.encode()) > 60000:
                raise ValueError("review comment exceeds GitHub size limit; inspect output artifact")
            api.publish(args.publish_pr, [body], REVIEW_MARKER)
        return int(bool(errors))
    if args.command in {"record", "sync-checkbox"}:
        if inventory.errors:
            raise ValueError("\n".join(inventory.errors))
        if args.command == "record":
            record(args, inventory, api)
        else:
            sync_checkbox(args, inventory, api)
        return 0
    all_actions = {action.id: action for action in [*base.actions, *inventory.actions]}
    receipts = read_receipts(args, Inventory(actions=list(all_actions.values())), api)
    result = plan(inventory, args.environment, receipts, base)
    chunks = markdown(result)
    emit(args, result.model_dump_json(indent=2) + "\n" if args.format == "json" else "\n".join(chunks))
    if args.publish_pr:
        if api is None:
            raise ValueError("--publish-pr requires --repo")
        api.publish(args.publish_pr, chunks, PLAN_MARKER)
    return int(bool(result.errors))


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "legacy":
        return legacy.main(args.arguments)
    api = None
    try:
        api = github(args) if args.command != "validate" else None
        return run(args, api)
    except (ValueError, OSError, httpx.HTTPError, KeyError) as exc:
        print(f"deployment-plan: {exc}", file=sys.stderr)
        return 1
    finally:
        if api:
            api.close()
