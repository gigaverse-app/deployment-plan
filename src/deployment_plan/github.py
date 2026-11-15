"""GitHub transport and append-only source-PR receipts.

No API failure is interpreted as an empty history. Human writers must have
repository write permission; the explicitly trusted workflow bot may record
an operator on whose behalf the workflow has already checked permission.
"""

import base64
import binascii
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from deployment_plan.models import Action, Receipt

RECEIPT_MARKER = "<!-- deployment-plan:receipt:v1 -->"


def valid_blob(data: Any, sha: str) -> bool:
    """Cached PR data is usable only when its Git object identity verifies."""
    try:
        if data["encoding"] != "base64":
            return False
        content = base64.b64decode(data["content"])
        return hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest() == sha
    except (KeyError, TypeError, ValueError, binascii.Error):
        return False


def rate_limit_delay(response: httpx.Response, attempt: int) -> float | None:
    """Retry rejected requests, never treat a permission denial as throttling."""
    if response.status_code not in {403, 429}:
        return None
    headers = response.headers
    if response.status_code == 403 and not (
        headers.get("x-ratelimit-remaining") == "0" or "retry-after" in headers or "rate limit" in response.text.lower()
    ):
        return None
    try:
        if "retry-after" in headers:
            return max(0, float(headers["retry-after"])) + 1
        if headers.get("x-ratelimit-remaining") == "0" and "x-ratelimit-reset" in headers:
            return max(0, float(headers["x-ratelimit-reset"]) - time.time()) + 1
    except ValueError:
        pass
    return 60 * (2**attempt)


class User(BaseModel):
    login: str
    type: str = "User"


class Comment(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    body: str
    user: User
    html_url: str


class GitHub:
    def __init__(self, repository: str, token: str, *, client: httpx.Client | None = None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("repository must be owner/name")
        self.repository = repository
        self.client = client or httpx.Client(base_url="https://api.github.com", timeout=30)
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._permissions: dict[str, bool] = {}
        self._blobs: dict[str, Any] = {}
        cache = os.environ.get("DEPLOYMENT_PLAN_BLOB_CACHE")
        self._blob_cache = Path(cache) if cache else None

    def close(self) -> None:
        self.client.close()

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        match = re.fullmatch(rf"/repos/{re.escape(self.repository)}/git/blobs/([0-9a-f]{{40}})", path)
        sha = match[1] if method == "GET" and match and not kwargs else None
        cache_file = self._blob_cache / sha if self._blob_cache and sha else None
        if sha in self._blobs:
            return self._blobs[sha]
        if cache_file:
            try:
                cached = json.loads(cache_file.read_text())
                if valid_blob(cached, sha):
                    self._blobs[sha] = cached
                    return cached
            except (OSError, ValueError):
                pass  # Missing or damaged cache entries are recovered from GitHub.
        for attempt in range(3):
            response = self.client.request(method, path, headers=self.headers, **kwargs)
            delay = rate_limit_delay(response, attempt)
            if delay is None or attempt == 2:
                break
            print(f"GitHub rate limited {method}; retrying in {delay:.0f}s", file=sys.stderr)
            time.sleep(delay)
        response.raise_for_status()
        data = response.json() if response.content else None
        if sha and valid_blob(data, sha):
            self._blobs[sha] = data
            if cache_file:
                try:
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    cache_file.write_text(json.dumps(data))
                except OSError:
                    pass  # An unavailable cache cannot prevent validation.
        return data

    def comments(self, pr: int) -> list[Comment]:
        result = []
        page = 1
        while True:
            batch = self.request(
                "GET", f"/repos/{self.repository}/issues/{pr}/comments", params={"per_page": 100, "page": page}
            )
            if not isinstance(batch, list):
                raise ValueError("GitHub comments response must be a list")
            result.extend(Comment.model_validate(comment) for comment in batch)
            if len(batch) < 100:
                return result
            page += 1

    def can_write(self, login: str) -> bool:
        if not re.fullmatch(r"[A-Za-z0-9_\[\]-]+", login):
            return False
        if login not in self._permissions:
            try:
                data = self.request("GET", f"/repos/{self.repository}/collaborators/{login}/permission")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
                self._permissions[login] = False
                return False
            self._permissions[login] = data["permission"] in {"admin", "maintain", "write"}
        return self._permissions[login]

    def actor(self) -> str:
        return User.model_validate(self.request("GET", "/user")).login

    def trusted(self, comment: Comment) -> bool:
        if comment.user.login == "github-actions[bot]" and comment.user.type == "Bot":
            return True
        return self.can_write(comment.user.login)

    def receipts(self, actions: list[Action]) -> list[Receipt]:
        by_pr: dict[int, set[str]] = {}
        for action in actions:
            if action.source_pr is None:
                raise ValueError(f"{action.id}: source_pr is required for GitHub persistence")
            by_pr.setdefault(action.source_pr, set()).add(action.id)
        receipts = []
        for pr, ids in by_pr.items():
            for comment in self.comments(pr):
                if not comment.body.startswith(RECEIPT_MARKER + "\n") or not self.trusted(comment):
                    continue
                receipt = Receipt.model_validate_json(comment.body.split("\n", 1)[1])
                if receipt.action_id not in ids:
                    continue
                if comment.user.type != "Bot" and receipt.actor != comment.user.login:
                    raise ValueError(f"receipt actor does not match author: {comment.html_url}")
                receipts.append(receipt)
        return receipts

    def append(self, action: Action, receipt: Receipt) -> None:
        if receipt.action_id != action.id or receipt.revision != action.revision:
            raise ValueError("receipt must identify the current action revision")
        for previous in self.receipts([action]):
            if previous.operation_id == receipt.operation_id:
                if previous != receipt:
                    raise ValueError(f"operation {receipt.operation_id} has conflicting content")
                return
        body = RECEIPT_MARKER + "\n" + receipt.model_dump_json()
        created = Comment.model_validate(
            self.request("POST", f"/repos/{self.repository}/issues/{action.source_pr}/comments", json={"body": body})
        )
        # Confirm the persisted representation before telling an operator it succeeded.
        saved = Comment.model_validate(self.request("GET", f"/repos/{self.repository}/issues/comments/{created.id}"))
        if saved.body != body:
            raise ValueError(f"receipt read-back differs: {saved.html_url}")

    def publish(self, pr: int, bodies: list[str], marker: str, *, author: str = "github-actions[bot]") -> None:
        existing = [c for c in self.comments(pr) if c.body.startswith(marker) and c.user.login == author]
        existing.sort(key=lambda comment: comment.id)
        for index, body in enumerate(bodies):
            if index < len(existing):
                comment = existing[index]
                if comment.body != body:
                    self.request("PATCH", f"/repos/{self.repository}/issues/comments/{comment.id}", json={"body": body})
            else:
                self.request("POST", f"/repos/{self.repository}/issues/{pr}/comments", json={"body": body})
        # Only retire stale chunks after all replacements were saved successfully.
        for comment in existing[len(bodies) :]:
            self.request("DELETE", f"/repos/{self.repository}/issues/comments/{comment.id}")
