"""Tiny GitHub REST client (Python standard library only).

`request` returns (json, headers). `paginate` follows GitHub's `Link: rel="next"` header and raises
IncompleteError if the collection cannot be read completely, so callers can fail closed.
"""
import json
import re
import urllib.request

API = "https://api.github.com"
_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


class IncompleteError(RuntimeError):
    """A paginated collection could not be read completely."""


class GitHub:
    def __init__(self, token, api=API):
        self.token, self.api = token, api

    def request(self, method, path, body=None):
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(self.api + path, data=data, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return (json.loads(raw) if raw else None), {k.lower(): v for k, v in resp.headers.items()}

    def call(self, method, path, body=None):
        return self.request(method, path, body)[0]


def next_path(headers, api=API):
    m = _NEXT.search((headers or {}).get("link", ""))
    if not m:
        return None
    url = m.group(1)
    if not url.startswith(api + "/"):
        raise IncompleteError("pagination link points outside the API")
    return url[len(api):]


def paginate(gh, path, key=None, max_pages=10):
    """All items of a list endpoint. `key` names the array for wrapped responses
    (e.g. "check_runs"); then `total_count` must equal the number of items read."""
    sep = "&" if "?" in path else "?"
    page_path, items, total = f"{path}{sep}per_page=100", [], None
    for _ in range(max_pages):
        data, headers = gh.request("GET", page_path)
        if key is None:
            if not isinstance(data, list):
                raise IncompleteError(f"expected a list from {path}")
            items.extend(data)
        else:
            if not isinstance(data, dict) or not isinstance(data.get(key), list):
                raise IncompleteError(f"expected '{key}' from {path}")
            items.extend(data[key])
            total = data.get("total_count")
        page_path = next_path(headers)
        if page_path is None:
            if key is not None and total != len(items):
                raise IncompleteError(f"{path}: read {len(items)} of total_count {total}")
            return items
    raise IncompleteError(f"{path}: more than {max_pages} pages")
