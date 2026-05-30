import db
from tools import registry
from workers import worker_manager


def setup_function():
    db.init_db()
    with db.get_conn() as conn:
        conn.execute("DELETE FROM capability_registry")
    registry.register_builtin_tools()


def test_search_github_routes_to_web_worker(monkeypatch):
    monkeypatch.setattr(worker_manager.web_worker, "run_web_task", lambda task_id, desc: {"status": "ok", "task_id": task_id, "data": ["web"], "error": None})
    result = worker_manager.dispatch("t1", "search github issues for python")
    assert result["status"] == "ok"
    assert result["data"] == ["web"]


def test_repair_bug_routes_to_repair_worker():
    result = worker_manager.dispatch("t2", "repair bug in repository")
    assert result["status"] == "ok"
    assert result["data"]["worker"] == "repair"


def test_unknown_task_returns_needs_forge():
    result = worker_manager.dispatch("t3", "zzzz qqqq no existing worker")
    assert result["status"] == "needs_forge"
    assert "suggested_prompt" in result


def test_needs_forge_never_calls_forge(monkeypatch):
    called = {"forge": False}

    def fake_register(*args, **kwargs):
        called["forge"] = True

    monkeypatch.setattr("workers.forge_worker.run_forge_task", fake_register)
    result = worker_manager.dispatch("t4", "unmatched brand new impossible capability")
    assert result["status"] == "needs_forge"
    assert called["forge"] is False
