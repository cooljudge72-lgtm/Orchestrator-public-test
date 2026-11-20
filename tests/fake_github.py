"""In-memory stand-in for the GitHub refs API (synthetic test double; no network)."""
import io
import json
import threading
import urllib.error


def http_error(code, message):
    return urllib.error.HTTPError("https://api.example/x", code, message, {},
                                  io.BytesIO(json.dumps({"message": message}).encode()))


class FakeGitHub:
    def __init__(self):
        self.refs, self.lock = {}, threading.Lock()
        self.create_error = self.delete_error = self.read_error = None
        self.lose_response_once = False

    def call(self, method, path, body=None):
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
            return {"ref": body["ref"]}
        if method == "GET" and "/git/ref/" in path:
            if self.read_error:
                raise self.read_error
            ref = "refs/" + path.split("/git/ref/", 1)[1]
            if ref not in self.refs:
                raise http_error(404, "Not Found")
            return {"ref": ref, "object": {"sha": self.refs[ref], "type": "commit"}}
        if method == "GET" and "/git/matching-refs/" in path:
            prefix = "refs/" + path.split("/git/matching-refs/", 1)[1]
            return [{"ref": r} for r in self.refs if r.startswith(prefix)]
        if method == "DELETE" and "/git/refs/" in path:
            if self.delete_error:
                raise self.delete_error
            ref = "refs/" + path.split("/git/refs/", 1)[1]
            with self.lock:
                if ref not in self.refs:
                    raise http_error(422, "Reference does not exist")
                del self.refs[ref]
            return None
        raise AssertionError(f"unexpected call {method} {path}")
