from revenue import bounty_pipeline


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_find_returns_correct_structure(monkeypatch):
    payload = {
        "items": [
            {
                "title": "Fix Python tests",
                "html_url": "https://github.com/o/r/issues/1",
                "repository_url": "https://api.github.com/repos/o/r",
                "body": "Please add tests",
                "labels": [{"name": "bounty"}],
                "comments": 1,
            }
        ]
    }
    def fake_get(url, *a, **k):
        if "search/issues" in url and "type:pr" not in (k.get("params") or {}).get("q", ""):
            return FakeResponse(payload)
        if url.endswith("/readme") or "/contents/tests" in url:
            return FakeResponse({})
        if "/contents/" in url:
            raise RuntimeError("missing")
        if "/repos/o/r" in url:
            return FakeResponse({"language": "Python"})
        return FakeResponse({"total_count": 0, "items": []})

    monkeypatch.setattr(bounty_pipeline.requests, "get", fake_get)
    issue = bounty_pipeline.find_bounty_issues()[0]
    assert issue["title"] == "Fix Python tests"
    assert issue["repo_url"] == "https://github.com/o/r"
    assert issue["labels"] == ["bounty"]


def test_score_ranks_python_tests_higher():
    good = {"title": "Python bug", "body": "README includes pytest tests and clear steps " * 5, "labels": ["good-first-issue"]}
    weak = {"title": "Bug", "body": "broken", "labels": [], "competing_prs": True}
    assert bounty_pipeline.score_issue(good) > bounty_pipeline.score_issue(weak)


def test_pipeline_cycle_runs_without_exception(monkeypatch):
    monkeypatch.setattr(
        bounty_pipeline,
        "find_bounty_issues",
        lambda max=20: [{"title": "Python tests", "url": "https://github.com/o/r/issues/2", "repo_url": "https://github.com/o/r", "body": "pytest tests README " * 10, "labels": ["bounty"]}],
    )
    result = bounty_pipeline.run_pipeline_cycle()
    assert result["found"] == 1
    assert result["queued"] == 1
    assert len(result["top_issues"]) == 1
