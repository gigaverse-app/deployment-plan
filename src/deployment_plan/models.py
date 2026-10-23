"""Canonical authoring and receipt contracts. Definitions never execute commands."""

import hashlib
import json
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Phase(StrEnum):
    BEFORE = "before"
    DURING = "during"
    AFTER = "after"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Action(Contract):
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,159}$")
    instructions: str = Field(min_length=1, max_length=20000)
    owner: str = Field(min_length=1, max_length=200)
    environments: tuple[str, ...] = Field(min_length=1)
    phase: Phase
    source_pr: int | None = Field(default=None, gt=0)
    references: tuple[str, ...] = ()

    @field_validator("instructions", "owner")
    @classmethod
    def meaningful_text(cls, value: str) -> str:
        value = value.replace("\r\n", "\n").strip()
        if not value:
            raise ValueError("must contain non-whitespace text")
        return value

    @field_validator("environments")
    @classmethod
    def unique_environments(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        import re

        if any(not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}", v) for v in values):
            raise ValueError("environment names must be simple identifiers")
        if len(set(values)) != len(values):
            raise ValueError("environments must be unique")
        return tuple(sorted(values))

    @property
    def revision(self) -> str:
        # Operational scope and instructions define what the operator acknowledged.
        # Owner and reference edits do not invalidate work already performed.
        payload = self.model_dump(mode="json", include={"instructions", "environments", "phase"})
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class Inventory(BaseModel):
    actions: list[Action] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class Transition(StrEnum):
    COMPLETE = "complete"
    REOPEN = "reopen"
    RETIRE = "retire"


class Receipt(Contract):
    """An immutable transition. Parents are the observed frontier, not timestamps."""

    operation_id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,159}$")
    action_id: str
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    environment: str
    transition: Transition
    parents: tuple[str, ...] = ()
    actor: str = Field(min_length=1)
    evidence: str = Field(min_length=1, max_length=8000)
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return value

    @field_validator("evidence", "actor")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must contain non-whitespace text")
        return value.strip()


class Status(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    RETIRED = "retired"
    CONFLICT = "conflict"


class Item(Contract):
    action: Action
    environment: str
    status: Status = Status.PENDING
    frontier: tuple[str, ...] = ()
    carried: bool = False
    missing: bool = False


class Plan(BaseModel):
    environment: str
    items: list[Item] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    @property
    def pending(self) -> list[Item]:
        return [item for item in self.items if item.status in {Status.PENDING, Status.CONFLICT}]
