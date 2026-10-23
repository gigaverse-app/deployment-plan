"""Trusted GitHub event runner. Consumer repositories are read strictly as data."""

import argparse
import base64
import json
import os
import tempfile
from pathlib import Path, PurePosixPath

from deployment_plan.cli import run, sync_checkbox
from deployment_plan.github import GitHub
from deployment_plan.manifest import load
from deployment_plan.models import Inventory
from deployment_plan.planning import plan
from deployment_plan.render import PLAN_MARKER, markdown


def snapshot(api: GitHub, ref: str, manifest: str, destination: Path) -> Path:
    """Read a bounded manifest subtree without checking out or importing PR code."""
    prefix = PurePosixPath(manifest)
    if prefix.is_absolute() or ".." in prefix.parts or not prefix.parts:
        raise ValueError("manifest must be a relative repository path")
    tree = api.request("GET", f"/repos/{api.repository}/git/trees/{ref}", params={"recursive": 1})
    if tree.get("truncated"):
        raise ValueError("GitHub truncated the repository tree; use a smaller manifest data fetch")
    destination.mkdir(parents=True, exist_ok=True)
    count = 0
    total = 0
    for entry in tree["tree"]:
        path = PurePosixPath(entry["path"])
        if path != prefix and prefix not in path.parents:
            continue
        if path.suffix not in {".yaml", ".yml"} or entry["type"] != "blob":
            continue
        if ".." in path.parts or path.is_absolute() or entry["mode"] not in {"100644", "100755"}:
            raise ValueError(f"manifest must be a regular file: {path}")
        if entry.get("size", 0) > 1_000_000:
            raise ValueError(f"manifest is larger than 1 MB: {path}")
        blob = api.request("GET", f"/repos/{api.repository}/git/blobs/{entry['sha']}")
        if blob["encoding"] != "base64":
            raise ValueError(f"unexpected blob encoding: {path}")
        content = base64.b64decode(blob["content"])
        total += len(content)
        count += 1
        if total > 10_000_000 or count > 1000:
            raise ValueError("manifest inventory exceeds 10 MB or 1000 fragments")
        target = destination / str(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    result = destination / manifest
    # A genuinely absent directory on the base is an empty initial inventory.
    # Head absence is checked by the caller; malformed existing files are not hidden.
    return result


def execute(api: GitHub, event: dict, manifest: str, environments: dict[str, str], directory: Path) -> None:
    if "pull_request" in event:
        pr = event["pull_request"]
        number = event["number"]
        head_repo = pr["head"]["repo"]["full_name"]
        head_api = api if head_repo == api.repository else GitHub(head_repo, os.environ["GH_TOKEN"])
        try:
            head = snapshot(head_api, pr["head"]["sha"], manifest, directory / "head")
        finally:
            if head_api is not api:
                head_api.close()
        base = snapshot(api, pr["base"]["sha"], manifest, directory / "base")
        inventory = load(head)
        previous = load(base) if base.exists() else Inventory()
        environment = environments.get(pr["base"]["ref"])
        if environment:
            actions = {action.id: action for action in [*previous.actions, *inventory.actions]}
            receipts = api.receipts(list(actions.values()))
            result = plan(inventory, environment, receipts, previous)
            api.publish(number, markdown(result), PLAN_MARKER)
            if result.errors:
                raise ValueError("\n".join(result.errors))
        else:
            args = argparse.Namespace(
                command="review",
                manifest=head,
                base_manifest=base if base.exists() else None,
                output=directory / "review.md",
                publish_pr=number,
                repo=api.repository,
            )
            if run(args, api):
                raise ValueError("deployment action review contains validation errors")
        return
    if event.get("action") == "edited" and "comment" in event:
        # The source PR may be months old. Use the current promotion head inventory.
        if not event["comment"]["body"].startswith(PLAN_MARKER):
            return
        pr = api.request("GET", f"/repos/{api.repository}/pulls/{event['issue']['number']}")
        environment = environments.get(pr["base"]["ref"])
        if environment is None:
            raise ValueError("completion event is not on a configured promotion branch")
        if pr["head"]["repo"]["full_name"] != api.repository:
            raise ValueError("completion edits on fork promotion plans are unsupported")
        head = snapshot(api, pr["head"]["sha"], manifest, directory / "head")
        inventory = load(head)
        if inventory.errors:
            raise ValueError("\n".join(inventory.errors))
        event_file = directory / "event.json"
        event_file.write_text(json.dumps(event))
        sync_checkbox(argparse.Namespace(event=event_file), inventory, api)
        receipts = api.receipts(inventory.actions)
        api.publish(event["issue"]["number"], markdown(plan(inventory, environment, receipts)), PLAN_MARKER)


def main() -> None:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    manifest = os.environ.get("DEPLOYMENT_PLAN_MANIFEST", "deployment/followups")
    environments = json.loads(
        os.environ.get("DEPLOYMENT_PLAN_ENVIRONMENTS", '{"staging":"staging","production":"production"}')
    )
    api = GitHub(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"])
    try:
        with tempfile.TemporaryDirectory(prefix="deployment-plan-") as path:
            execute(api, event, manifest, environments, Path(path))
    finally:
        api.close()


if __name__ == "__main__":
    main()
