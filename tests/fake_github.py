"""In-memory stand-in for the GitHub REST API (synthetic test double; no network).

Responses follow the shapes in GitHub's REST API description (git-tag, git-ref, paginated lists
with Link headers). Requests are recorded so contract tests can check exact bodies.
"""
import io
import json
import threading
import urllib.error

API = "https://api.github.com"
TAG_REQUEST_KEYS = {"tag", "message", "object", "type"}          # required by POST /git/tags
TAG_OPTIONAL_KEYS = {"tagger"}


def http_error(code, message):
    return urllib.error.HTTPError(f"{API}/x", code, message, {}, io.BytesIO(json.dumps({"message": message}).encode()))


UNSET = object()


class Page:
    """A routed GET response, optionally with a next page."""
    def __init__(self, data, next_path=None):
        self.data, self.next_path = data, next_path


class FakeGitHub:
    def __init__(self, repo="example-owner/example-repo", tagger_in_response=True):
        self.repo, self.tagger_in_response = repo, tagger_in_response
        self.refs, self.tags, self.routes, self.requests = {}, {}, {}, []
        self.lock, self.tag_count = threading.Lock(), 0
        self.create_error = self.delete_error = self.read_error = None
        self.lose_response_once = False
        self.tag_response_override = self.ref_response_override = UNSET

    def call(self, method, path, body=None):
        return self.request(method, path, body)[0]

    def _ref_obj(self, ref):
        sha = self.refs[ref]
        kind = "tag" if sha in self.tags else "commit"
        return {"ref": ref, "node_id": "REF_x", "url": f"{API}/repos/{self.repo}/git/{ref}",
                "object": {"type": kind, "sha": sha, "url": f"{API}/repos/{self.repo}/git/{kind}s/{sha}"}}

    def request(self, method, path, body=None):
        self.requests.append((method, path, body))
        if method == "GET" and path in self.routes:
            value = self.routes[path]
            if isinstance(value, Exception):
                raise value
            if isinstance(value, Page):
                headers = {"link": f'<{API}{value.next_path}>; rel="next"'} if value.next_path else {}
                return value.data, headers
            return value, {}
        if method == "POST" and path.endswith("/git/tags"):
            keys = set(body)
            if not TAG_REQUEST_KEYS <= keys or keys - TAG_REQUEST_KEYS - TAG_OPTIONAL_KEYS or body["type"] != "commit":
                raise http_error(422, "Invalid request.")
            with self.lock:
                self.tag_count += 1
                sha = f"{self.tag_count:040x}"
            tag = {"node_id": "TAG_x", "tag": body["tag"], "sha": sha, "url": f"{API}/repos/{self.repo}/git/tags/{sha}",
                   "message": body["message"] + "\n",                       # git stores a trailing newline
                   "object": {"type": body["type"], "sha": body["object"], "url": f"{API}/repos/{self.repo}/git/commits/{body['object']}"},
                   "verification": {"verified": False, "reason": "unsigned", "signature": None, "payload": None}}
            if self.tagger_in_response:
                tag["tagger"] = {"name": "github-actions[bot]", "email": "noreply@example.invalid", "date": "2026-11-21T09:00:01Z"}
            self.tags[sha] = tag
            return (tag if self.tag_response_override is UNSET else self.tag_response_override), {}
        if method == "GET" and "/git/tags/" in path:
            return self.tags[path.rsplit("/", 1)[1]], {}
        if method == "POST" and path.endswith("/git/refs"):
            if self.create_error:
                raise self.create_error
            with self.lock:
                if body["ref"] in self.refs:
                    raise http_error(422, "Reference already exists")
                self.refs[body["ref"]] = body["sha"]
                if self.lose_response_once:
                    self.lose_response_once = False
                    raise ConnectionResetError("response lost after the ref was created")
            resp = self._ref_obj(body["ref"])
            return (resp if self.ref_response_override is UNSET else self.ref_response_override), {}
        if method == "GET" and "/git/ref/" in path:
            if self.read_error:
                raise self.read_error
            ref = "refs/" + path.split("/git/ref/", 1)[1]
            if ref not in self.refs:
                raise http_error(404, "Not Found")
            return self._ref_obj(ref), {}
        if method == "GET" and "/git/matching-refs/" in path:
            prefix = "refs/" + path.split("/git/matching-refs/", 1)[1]
            return [self._ref_obj(r) for r in self.refs if r.startswith(prefix)], {}
        if method == "DELETE" and "/git/refs/" in path:
            if self.delete_error:
                raise self.delete_error
            ref = "refs/" + path.split("/git/refs/", 1)[1]
            with self.lock:
                if ref not in self.refs:
                    raise http_error(422, "Reference does not exist")
                del self.refs[ref]
            return None, {}
        raise AssertionError(f"unexpected call {method} {path}")
