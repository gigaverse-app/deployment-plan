"""Load fragments or the original list ledger without discarding valid actions."""

from pathlib import Path

import yaml
from pydantic import Field, ValidationError

from deployment_plan.models import Action, Contract, Inventory, Phase


class Fragment(Contract):
    version: int = Field(ge=1, le=1)
    actions: list[Action]


def load(path: Path) -> Inventory:
    result = Inventory()
    if not path.exists():
        result.errors.append(f"manifest path does not exist: {path}")
        return result
    paths = sorted([*path.rglob("*.yaml"), *path.rglob("*.yml")]) if path.is_dir() else [path]
    for file in paths:
        try:
            raw = yaml.safe_load(file.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                # Late backfills are ordinary inventory entries, independent of commit ranges.
                result.actions.extend(legacy_actions(raw, file, result.errors))
            elif isinstance(raw, dict) and raw.get("version") == 1 and isinstance(raw.get("actions"), list):
                for index, candidate in enumerate(raw["actions"]):
                    try:
                        result.actions.append(Action.model_validate(candidate))
                    except ValidationError as exc:
                        result.errors.append(f"{file}: action {index + 1}: {exc}")
                if set(raw) != {"version", "actions"}:
                    result.errors.append(f"{file}: unknown fragment fields: {set(raw) - {'version', 'actions'}}")
            else:
                result.errors.append(f"{file}: expected version: 1 and actions list, or a legacy list ledger")
        except (OSError, ValueError, yaml.YAMLError) as exc:
            result.errors.append(f"{file}: {exc}")
    seen: set[str] = set()
    unique: list[Action] = []
    for action in result.actions:
        if action.id in seen:
            result.errors.append(f"duplicate action ID: {action.id}")
        else:
            seen.add(action.id)
            unique.append(action)
    result.actions = unique
    return result


def legacy_actions(raw: list[object], path: Path, errors: list[str]) -> list[Action]:
    from deployment_plan.legacy import FollowupEntry

    actions = []
    for index, candidate in enumerate(raw):
        try:
            entry = FollowupEntry.model_validate(candidate)
            for item in entry.followups:
                actions.append(
                    Action(
                        id=f"pr-{entry.pr}/{item.id}",
                        instructions=item.action,
                        owner=entry.owner,
                        environments=("staging", "production")
                        if item.environment.value == "both"
                        else (item.environment.value,),
                        phase=Phase(item.phase.value.removesuffix("-deploy")),
                        source_pr=entry.pr,
                        references=(entry.linear,),
                    )
                )
        except (ValidationError, ValueError) as exc:
            errors.append(f"{path}: entry {index + 1}: {exc}")
    return actions
