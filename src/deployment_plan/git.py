"""Explicit Git operations. No issue-number heuristics or application dependencies."""

import re
import subprocess
from pathlib import Path


def pull_request_numbers(base: str, head: str, cwd: Path | None = None) -> set[int]:
    if base == head:
        return set()
    subjects = subprocess.check_output(
        ["git", "log", "--format=%s", f"{base}..{head}", "--"], cwd=cwd, text=True
    ).splitlines()
    numbers: set[int] = set()
    for subject in subjects:
        if subject.startswith('Revert "'):
            continue
        match = re.search(r"\(#(\d+)\)$", subject) or re.match(r"Merge pull request #(\d+)\b", subject)
        if match:
            numbers.add(int(match.group(1)))
    return numbers
