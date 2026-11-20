"""Tiny GitHub REST client (Python standard library only)."""
import json
import urllib.request

API = "https://api.github.com"


class GitHub:
    def __init__(self, token, api=API):
        self.token, self.api = token, api

    def call(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.api + path, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
