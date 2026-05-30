import db
from tools import registry


def setup_function():
    db.init_db()
    with db.get_conn() as conn:
        conn.execute("DELETE FROM capability_registry")


def test_register_retrieve_round_trip():
    registry.register_tool("alpha", "does alpha work", "x.y", "built")
    tool = registry.get_tool("alpha")
    assert tool is not None
    assert tool["tool_name"] == "alpha"
    assert tool["description"] == "does alpha work"
    assert tool["entry_point"] == "x.y"


def test_duplicate_register_updates_not_duplicates():
    registry.register_tool("alpha", "old", "old.entry", "built")
    registry.register_tool("alpha", "new", "new.entry", "worker")
    tools = registry.list_tools()
    assert len([tool for tool in tools if tool["tool_name"] == "alpha"]) == 1
    assert registry.get_tool("alpha")["description"] == "new"


def test_find_tool_for_task_hits_and_misses():
    registry.register_tool("web_search", "search web pages and github issues", "workers.web_worker.run_web_task", "worker")
    assert registry.find_tool_for_task("please search github")["tool_name"] == "web_search"
    assert registry.find_tool_for_task("zzzz qqqq nohit") is None


def test_use_count_increments():
    registry.register_tool("alpha", "does alpha work", "x.y", "built")
    registry.record_tool_use("alpha")
    registry.record_tool_use("alpha")
    assert registry.get_tool("alpha")["use_count"] == 2
