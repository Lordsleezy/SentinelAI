"""
Validation for SentinelAI orchestration OS expansion.
"""

import os
import time
from pathlib import Path

import db
import orchestration as orch
import queue_manager as qm
from internet_runtime import get_research_runtime
from memory.filesystem_index import get_filesystem_indexer
from memory.persistent_memory import initialize_memory
from model_router import get_model_router
from reflection import ReflectionEngine
from tool_registry import get_tool_registry


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    print("SentinelAI Runtime Expansion Validation")
    print("=" * 60)

    db.init_db()
    qm.initialize_queue()
    initialize_memory()
    orchestrator = orch.initialize_orchestration()

    print("[1/8] Persistent vector memory")
    memory_id = initialize_memory().remember(
        "project",
        "SentinelAI uses LangGraph, CrewAI, SQLite checkpoints, and supervised workflow approvals.",
        {"test": True},
    )
    results = initialize_memory().recall("project", "CrewAI workflow approvals", limit=3)
    assert_true(memory_id is not None, "memory id missing")
    assert_true(results and results[0]["score"] > 0, "memory retrieval failed")
    print("  OK")

    print("[2/8] Filesystem awareness")
    index_result = get_filesystem_indexer().index_workspace(str(Path.cwd()), max_files=40)
    files = get_filesystem_indexer().list_workspace_files(str(Path.cwd()), limit=20)
    assert_true(index_result["files_indexed"] > 0, "no files indexed")
    assert_true(files, "indexed files not persisted")
    print("  OK")

    print("[3/8] Internet research abstraction")
    research = get_research_runtime().search("SentinelAI orchestration runtime", limit=2, persist=False)
    assert_true("providers" in research, "provider status missing")
    assert_true("results" in research, "research results field missing")
    print("  OK")

    print("[4/8] Model routing")
    route = get_model_router().route("coding", "patch a Python workflow bug")
    assert_true(route["provider"] == "ollama", "coding route should prefer local ollama")
    assert_true(route["model"], "model route missing model")
    print("  OK")

    print("[5/8] Tool orchestration")
    tools = get_tool_registry().list_tools()
    assert_true("git_status" in tools, "git tool missing")
    tool_result = get_tool_registry().run_tool("list_files", root=str(Path.cwd()), limit=5)
    assert_true(tool_result.success, "list_files tool failed")
    print("  OK")

    print("[6/8] Expanded agents route correctly")
    cases = {
        "plan task execution": "PlannerAgent",
        "index filesystem workspace": "FilesystemAgent",
        "search internet documentation": "ResearchCoordinatorAgent",
        "reflect on workflow": "ReflectionAgent",
        "retrieve memory": "MemoryAgent",
    }
    for goal, expected_agent in cases.items():
        submitted = orchestrator.submit_workflow(
            goal=f"{goal} {time.time()}",
            workflow_type="general",
            requires_approval=False,
            enqueue=False,
        )
        state = orchestrator.run_workflow(submitted["workflow_id"])
        assert_true(state["assigned_agent"] == expected_agent, f"{goal} routed to {state['assigned_agent']}")
    print("  OK")

    print("[7/8] Reflection system")
    submitted = orchestrator.submit_workflow(
        goal=f"runtime reflection validation {time.time()}",
        workflow_type="debugging",
        requires_approval=False,
        enqueue=False,
    )
    state = orchestrator.run_workflow(submitted["workflow_id"])
    reflection = ReflectionEngine().reflect(state)
    assert_true(reflection["score"]["score"] >= 0, "reflection score missing")
    assert_true(reflection["improvements"], "reflection improvements missing")
    print("  OK")

    print("[8/8] Protected API surface")
    os.environ["SENTINELAI_AUTH_TOKEN"] = "expansion-test-token"
    import desktop_app

    client = desktop_app.app.test_client()
    unauthorized = client.post("/api/research/search", json={"query": "test"})
    authorized = client.post(
        "/api/model-router/route",
        json={"task_type": "coding", "prompt": "fix tests"},
    )
    assert_true(unauthorized.status_code == 401, "research endpoint should require auth")
    assert_true(authorized.status_code == 200, "model router endpoint failed")
    print("  OK")

    print("\nALL RUNTIME EXPANSION TESTS PASSED")


if __name__ == "__main__":
    main()
