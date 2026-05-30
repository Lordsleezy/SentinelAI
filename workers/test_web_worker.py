from workers import web_worker


class FakeResponse:
    def __init__(self, text="", json_data=None):
        self.text = text
        self._json = json_data

    def raise_for_status(self):
        return None

    def json(self):
        return self._json


def test_search_returns_correct_fields(monkeypatch):
    html = """
    <div class="result">
      <h2 class="result__title"><a href="https://example.com">Example</a></h2>
      <a class="result__snippet">Snippet here</a>
    </div>
    """
    monkeypatch.setattr(web_worker.requests, "get", lambda *a, **k: FakeResponse(html))
    results = web_worker.search_web("example")
    assert results == [{"title": "Example", "url": "https://example.com", "snippet": "Snippet here"}]


def test_fetch_strips_scripts(monkeypatch):
    html = "<html><head><title>T</title><script>bad()</script></head><body><main>Hello</main><a href='/x'>X</a></body></html>"
    monkeypatch.setattr(web_worker.requests, "get", lambda *a, **k: FakeResponse(html))
    page = web_worker.fetch_page("https://example.com")
    assert page["title"] == "T"
    assert "bad()" not in page["text"]
    assert page["links"][0]["url"] == "https://example.com/x"


def test_github_issues_correct_structure(monkeypatch):
    payload = [{"number": 1, "title": "Bug", "html_url": "https://github.com/o/r/issues/1", "labels": [{"name": "bug"}], "state": "open"}]
    monkeypatch.setattr(web_worker.requests, "get", lambda *a, **k: FakeResponse(json_data=payload))
    issues = web_worker.find_github_issues("o/r")
    assert issues[0]["number"] == 1
    assert issues[0]["labels"] == ["bug"]


def test_unknown_task_returns_error_not_exception():
    result = web_worker.run_web_task("t1", "do something mysterious")
    assert result["status"] == "error"
    assert result["task_id"] == "t1"
    assert result["error"]
