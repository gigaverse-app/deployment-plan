"""Small GitHub HTTP fixture on respx; production orchestration stays intact."""

import base64
import json
import re

import httpx
import respx


class GitHubHarness:
    def __init__(self, repository="example/service"):
        self.repository = repository
        self.comments: dict[int, list[dict]] = {}
        self.files: dict[str, dict[str, str]] = {}
        self.pulls: dict[int, dict] = {}
        self.merge_base = "base"
        self.permissions = {"operator": "write", "visitor": "read"}
        self.next_id = 1
        self.router = respx.mock(assert_all_called=False)

    def __enter__(self):
        self.router.start()
        self.router.route().mock(side_effect=self.respond)
        return self

    def __exit__(self, *args):
        self.router.stop()

    def respond(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        prefix = f"/repos/{self.repository}"
        if path == "/user":
            return httpx.Response(200, json={"login": "operator"})
        if path.startswith(prefix + "/compare/"):
            return httpx.Response(200, json={"merge_base_commit": {"sha": self.merge_base}})
        if match := re.fullmatch(prefix + r"/collaborators/([^/]+)/permission", path):
            login = match[1]
            return (
                httpx.Response(200, json={"permission": self.permissions[login]})
                if login in self.permissions
                else httpx.Response(404)
            )
        if match := re.fullmatch(prefix + r"/git/trees/([^/]+)", path):
            files = self.files[match[1]]
            return httpx.Response(
                200,
                json={
                    "truncated": False,
                    "tree": [
                        {
                            "path": key,
                            "type": "blob",
                            "mode": "100644",
                            "sha": match[1] + "_" + str(index),
                            "size": len(value),
                        }
                        for index, (key, value) in enumerate(files.items())
                    ],
                },
            )
        if match := re.fullmatch(prefix + r"/git/blobs/([^/]+)", path):
            ref, index = match[1].rsplit("_", 1)
            content = list(self.files[ref].values())[int(index)]
            return httpx.Response(
                200, json={"encoding": "base64", "content": base64.b64encode(content.encode()).decode()}
            )
        if match := re.fullmatch(prefix + r"/pulls/(\d+)", path):
            return httpx.Response(200, json=self.pulls[int(match[1])])
        if match := re.fullmatch(prefix + r"/issues/(\d+)/comments", path):
            comments = self.comments.setdefault(int(match[1]), [])
            if request.method == "GET":
                page = int(request.url.params.get("page", "1"))
                return httpx.Response(200, json=comments[(page - 1) * 100 : page * 100])
            if request.method == "POST":
                comment = {
                    "id": self.next_id,
                    "body": json.loads(request.content)["body"],
                    "user": {"login": "github-actions[bot]", "type": "Bot"},
                    "html_url": f"https://github.com/{self.repository}/pull/{match[1]}#issuecomment-{self.next_id}",
                }
                comments.append(comment)
                self.next_id += 1
                return httpx.Response(201, json=comment)
        if match := re.fullmatch(prefix + r"/issues/comments/(\d+)", path):
            for comments in self.comments.values():
                for comment in comments:
                    if comment["id"] == int(match[1]):
                        if request.method == "PATCH":
                            comment["body"] = json.loads(request.content)["body"]
                        elif request.method == "DELETE":
                            comments.remove(comment)
                            return httpx.Response(204)
                        return httpx.Response(200, json=comment)
        raise AssertionError(f"Unexpected GitHub request: {request.method} {request.url}")
