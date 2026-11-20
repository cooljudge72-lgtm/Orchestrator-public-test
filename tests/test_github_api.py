"""Pagination fails closed; requests with a body declare JSON."""
import json
import unittest
from unittest import mock

from lockcheck.github_api import GitHub, IncompleteError, next_path, paginate
from tests.fake_github import FakeGitHub, Page

P = "/repos/o/r/pulls/2/files"


class TestPagination(unittest.TestCase):
    def test_follows_link_header_to_the_end(self):
        gh = FakeGitHub()
        gh.routes[f"{P}?per_page=100"] = Page([{"n": 1}], next_path=f"{P}?per_page=100&page=2")
        gh.routes[f"{P}?per_page=100&page=2"] = Page([{"n": 2}])
        self.assertEqual([x["n"] for x in paginate(gh, P)], [1, 2])

    def test_truncated_collection_raises(self):
        gh = FakeGitHub()
        gh.routes[f"{P}?per_page=100"] = Page([{"n": 1}], next_path=f"{P}?per_page=100&page=2")
        gh.routes[f"{P}?per_page=100&page=2"] = Page([{"n": 2}], next_path=f"{P}?per_page=100&page=2")  # never ends
        with self.assertRaises(IncompleteError):
            paginate(gh, P, max_pages=3)

    def test_total_count_must_match(self):
        gh = FakeGitHub()
        path = "/repos/o/r/commits/x/check-runs"
        gh.routes[f"{path}?per_page=100"] = Page({"total_count": 3, "check_runs": [{"id": 1}, {"id": 2}]})
        with self.assertRaises(IncompleteError):
            paginate(gh, path, key="check_runs")
        gh.routes[f"{path}?per_page=100"] = Page({"total_count": 2, "check_runs": [{"id": 1}, {"id": 2}]})
        self.assertEqual(len(paginate(gh, path, key="check_runs")), 2)

    def test_wrong_shape_raises(self):
        gh = FakeGitHub()
        gh.routes[f"{P}?per_page=100"] = Page({"message": "Not Found"})
        with self.assertRaises(IncompleteError):
            paginate(gh, P)

    def test_foreign_pagination_link_rejected(self):
        with self.assertRaises(IncompleteError):
            next_path({"link": '<https://evil.example/x>; rel="next"'})
        self.assertIsNone(next_path({}))


class TestRequestShape(unittest.TestCase):
    def test_body_requests_declare_json_and_api_version(self):
        captured = {}

        class Resp:
            headers = {"Link": ""}
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"ok": true}'

        def fake_urlopen(req, timeout):
            captured["headers"] = {k.lower(): v for k, v in req.header_items()}
            captured["data"] = req.data
            return Resp()

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            data, headers = GitHub("t").request("POST", "/x", {"a": 1})
        self.assertEqual(data, {"ok": True})
        self.assertEqual(captured["headers"]["content-type"], "application/json; charset=utf-8")
        self.assertEqual(captured["headers"]["x-github-api-version"], "2022-11-28")
        self.assertEqual(json.loads(captured["data"]), {"a": 1})


if __name__ == "__main__":
    unittest.main()
