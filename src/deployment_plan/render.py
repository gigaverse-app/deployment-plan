"""Bounded Markdown projections with machine identity separated from prose."""

import base64
import re

from pydantic import BaseModel

from deployment_plan.models import Item, Plan, Status

PLAN_MARKER = "<!-- deployment-plan:plan:v1 -->"


class Checkbox(BaseModel):
    action_id: str
    revision: str
    environment: str
    parents: tuple[str, ...]

    @classmethod
    def from_item(cls, item: Item) -> "Checkbox":
        return cls(
            action_id=item.action.id, revision=item.action.revision, environment=item.environment, parents=item.frontier
        )

    def encoded(self) -> str:
        return base64.urlsafe_b64encode(self.model_dump_json().encode()).decode()


def code(text: str) -> str:
    width = max([2, *(len(match) for match in re.findall(r"`+", text))]) + 1
    fence = "`" * width
    return f"{fence}\n{text}\n{fence}"


def item_markdown(item: Item) -> str:
    checked = "x" if item.status in {Status.COMPLETE, Status.RETIRED} else " "
    flags = [item.status.value]
    if item.carried:
        flags.append("carried forward")
    if item.missing:
        flags.append("definition removed")
    origin = f"PR #{item.action.source_pr}" if item.action.source_pr else "unbound source PR"
    line = f"- [{checked}] `{item.action.id}` · {item.action.phase.value} · {origin} · {', '.join(flags)} <!-- dp:item:{Checkbox.from_item(item).encoded()} -->"
    details = code(f"Owner: {item.action.owner}\n\n{item.action.instructions}")
    return line + "\n" + "\n".join("  " + part for part in details.splitlines()) + "\n"


def markdown(result: Plan, *, limit: int = 60000) -> list[str]:
    heading = f"{PLAN_MARKER}\n## Deployment plan: {result.environment}\n\n"
    footer = "\nCompletion is per environment and instruction revision. Check a box after performing its action.\n"
    blocks = ["> **Plan needs attention**\n\n" + code(error) + "\n" for error in result.errors]
    blocks.extend(item_markdown(item) for item in result.items)
    if not blocks:
        blocks = ["No deployment actions are recorded for this environment.\n"]
    return chunk_blocks(heading, blocks, footer, limit=limit)


def chunk_blocks(heading: str, blocks: list[str], footer: str, *, limit: int = 60000) -> list[str]:
    chunks = []
    current = heading
    for block in blocks:
        if len((heading + block + footer).encode()) > limit:
            raise ValueError(
                "one deployment item exceeds the comment limit; shorten its instructions or link a runbook"
            )
        if len((current + block + footer).encode()) > limit:
            chunks.append(current + footer)
            current = heading
        current += block + "\n"
    chunks.append(current + footer)
    return chunks


def checkboxes(body: str) -> dict[str, tuple[Checkbox, bool]]:
    result = {}
    if not body.startswith(PLAN_MARKER):
        return result
    for line in body.splitlines():
        match = re.fullmatch(r"- \[([ xX])\] .* <!-- dp:item:([A-Za-z0-9_=-]+) -->", line)
        if match:
            checkbox = Checkbox.model_validate_json(base64.urlsafe_b64decode(match.group(2)))
            if checkbox.action_id in result:
                raise ValueError(f"duplicate checkbox for {checkbox.action_id}")
            result[checkbox.action_id] = (checkbox, match.group(1).lower() == "x")
    return result
