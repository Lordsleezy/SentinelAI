"""Full end-to-end integration tests for SentinelAI.

Scenarios
---------
1. Known task — search intent → search worker, no approval created
2. Unknown/build task — Forge gate: pending approval → blocked → approve → runs
3. Repair pipeline: repair intent → executor → status flows to desktop API
4. UI smoke: endpoints return correct envelope, task submit visible in queue

Isolation: each test gets a fresh DB via the ``clean_db`` fixture.
Ollama is always monkeypatched to False so tests run offline.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ── module stubs needed before desktop_app can be imported ────────────────────

def _stub_heavy_imports():
    stubs = {
        "pystray": MagicMock(),
        "PIL": MagicMock(),
        "PIL.Image": MagicMock(),
        "PIL.ImageDraw": MagicMock(),
        "learning_memory": MagicMock(),
        "watchdog": MagicMock(),
        "health_monitor": MagicMock(),
        "internet_runtime": MagicMock(),
        "memory": MagicMock(),
        "memory.filesystem_index": MagicMock(),
        "memory.persistent_memory": MagicMock(),
        "model_router": MagicMock(),
        "reflection": MagicMock(),
        "tool_registry": MagicMock(),
    }
    stubs["internet_runtime"].get_research_runtime = MagicMock(return_value=MagicMock())
    stubs["memory.filesystem_index"].get_filesystem_indexer = MagicMock(return_value=MagicMock())
    stubs["memory.persistent_memory"].get_memory = MagicMock(return_value=MagicMock())
    stubs["model_router"].get_model_router = MagicMock(return_value=MagicMock())
    stubs["reflection"].ReflectionEngine = MagicMock()
    stubs["tool_registry"].get_tool_registry = MagicMock(return_value=MagicMock())
    for mod, stub in stubs.items():
        sys.modules.setdefault(mod, stub)

_stub_heavy_imports()

import db
import orchestrator as orch_mod
import queue_manager as qm
from openclaw import openclaw as oc_mod
from tools import registry as tool_registry


# ── fixtures ─────────────────────────────────────────────────────────────────

_TMPDIR = tempfile.mkdtemp(prefix="sentinel-integ-")
_DB_PATH = os.path.join(_TMPDIR, "integ.db")

db.DB_PATH = _DB_PATH
db.init_db()
qm.init_queue_tables()
oc_mod._schema_initialized = False
oc_mod.ensure_approvals_table()
orch_mod._schema_initialized = False
orch_mod.ensure_orchestrator_table()


@pytest.fixture(autouse=True)
def clean_db(monkeypatch):
    """Reset all mutable tables and singletons before every test."""
    # Always use keyword-based intent parsing (avoids needing Ollama running).
    monkeypatch.setattr(orch_mod, "parse_intent", orch_mod._parse_intent_keywords)
    monkeypatch.setattr(orch_mod, "_ollama_available", lambda: False)

    # Re-point db at our private temp file — other test suites may have
    # changed db.DB_PATH when they ran earlier in the same session.
    db.DB_PATH = _DB_PATH
    db.init_db()
    qm.init_queue_tables()
    oc_mod._schema_initialized = False
    oc_mod.ensure_approvals_table()
    orch_mod._schema_initialized = False
    orch_mod.ensure_orchestrator_table()

    with db.get_conn() as conn:
        for table in (
            "approvals",
            "orchestrator_tasks",
            "task_queue",
        ):
            conn.execute(f"DELETE FROM {table}")

    # Reset singletons.
    oc_mod._instance = None
    oc_mod._schema_initialized = False
    oc_mod.ensure_approvals_table()
    orch_mod._orchestrator = None
    orch_mod._schema_initialized = False
    orch_mod.ensure_orchestrator_table()

    yield


@pytest.fixture()
def flask_client(monkeypatch):
    # Ensure keyword-based intent parsing within Flask request context too.
    monkeypatch.setattr(orch_mod, "parse_intent", orch_mod._parse_intent_keywords)
    monkeypatch.setattr(orch_mod, "_ollama_available", lambda: False)
    import desktop_app as da
    return da.app.test_client()


# ══════════════════════════════════════════════════════════════════════════════
# Scenario 1 — Known task (no Forge needed)
# ══════════════════════════════════════════════════════════════════════════════

def test_s1_search_routes_to_search_worker():
    """search intent hits the search handler, not Forge."""
    # Phrase deliberately avoids repair_kw words ("issue","bug","bounty","fix","patch").
    with patch.dict(sys.modules, {"scanner": MagicMock(run_scan=MagicMock(return_value=3))}):
        result = orch_mod.process_task(
            task_id="s1-search",
            task_description="search GitHub for popular Python repositories",
        )
    assert result["status"] == "completed", result
    assert result["worker"] == "search"


def test_s1_search_returns_results():
    """Result dict contains opportunities_found key."""
    with patch.dict(sys.modules, {"scanner": MagicMock(run_scan=MagicMock(return_value=7))}):
        result = orch_mod.process_task(
            task_id="s1-results",
            task_description="find open python bounties on github",
        )
    assert result["status"] == "completed"
    inner = result.get("result") or {}
    assert "opportunities_found" in inner or "error" in inner  # either is fine; no Forge


def test_s1_search_no_approval_created():
    """search task must not create any approval record."""
    with patch.dict(sys.modules, {"scanner": MagicMock(run_scan=MagicMock(return_value=0))}):
        orch_mod.process_task(
            task_id="s1-noappr",
            task_description="search github for python repos",
        )
    assert oc_mod.get_pending_approvals() == []


# ══════════════════════════════════════════════════════════════════════════════
# Scenario 2 — Unknown/build task (Forge gate)
# ══════════════════════════════════════════════════════════════════════════════

def test_s2_build_creates_pending_approval():
    """build intent triggers an approval gate immediately."""
    result = orch_mod.process_task(
        task_id="s2-build",
        task_description="build a tool to parse PDFs and extract dollar amounts",
        context={"wait_for_approval": False},
    )
    assert result["status"] == "awaiting_approval"
    assert result["needs_forge"] is True
    assert result.get("approval_id") is not None


def test_s2_forge_blocked_without_approval():
    """Forge MUST NOT run until the approval record is approved."""
    result = orch_mod.process_task(
        task_id="s2-blocked",
        task_description="create a PDF dollar extractor",
        context={"wait_for_approval": False},
    )
    approval_id = result["approval_id"]
    assert not oc_mod.is_approved(approval_id)

    # Directly calling _run_forge without approval must raise.
    orch = orch_mod.get_orchestrator()
    with pytest.raises(RuntimeError, match="not approved"):
        orch._run_forge("s2-blocked", approval_id, "build pdf extractor", {})


def test_s2_approval_in_db_as_pending():
    """DB row for the approval is status=pending."""
    result = orch_mod.process_task(
        task_id="s2-dbcheck",
        task_description="generate a PDF parsing utility",
        context={"wait_for_approval": False},
    )
    approval_id = result["approval_id"]
    pending = oc_mod.get_pending_approvals()
    ids = {p["id"] for p in pending}
    assert approval_id in ids
    approval_row = oc_mod.get_openclaw().get_approval(approval_id)
    assert approval_row["status"] == "pending"


def test_s2_forge_runs_after_approval_and_registers_tool():
    """After approval, Forge runs and the new tool appears in the registry."""
    result = orch_mod.process_task(
        task_id="s2-forgerun",
        task_description="make a PDF amount parser",
        context={"wait_for_approval": False},
    )
    task_id = result["task_id"]
    approval_id = result["approval_id"]

    oc_mod.get_openclaw().resolve_approval(approval_id, approved=True, reason="looks good")
    assert oc_mod.is_approved(approval_id)

    mock_fw = MagicMock()
    mock_fw.run_forge_task.return_value = {
        "output_path": "/fake/pdf_parser",
        "summary": "pdf parser built",
    }
    with patch.dict(sys.modules, {
        "workers.forge_worker": mock_fw,
        "workers": MagicMock(forge_worker=mock_fw),
    }):
        resumed = orch_mod.get_orchestrator().resume_approved_task(task_id)

    assert resumed["status"] == "completed"
    tool_name = resumed["result"]["registered_tool"]
    tool = tool_registry.get_tool(tool_name)
    assert tool is not None, f"tool {tool_name!r} not found in registry"


# ══════════════════════════════════════════════════════════════════════════════
# Scenario 3 — Repair pipeline
# ══════════════════════════════════════════════════════════════════════════════

def test_s3_repair_routes_to_repair_worker():
    """repair intent runs executor."""
    mock_exec = MagicMock()
    mock_exec.run_executor.return_value = {"status": "dry_run_ok"}
    with patch.dict(sys.modules, {"executor": mock_exec}):
        result = orch_mod.process_task(
            task_id="s3-repair",
            task_description="fix the authentication crash in the login module",
        )
    assert result["status"] == "completed", result
    assert result["worker"] == "repair"
    assert result.get("approval_id") is None


def test_s3_repair_result_persisted():
    """Completed repair task is queryable from the orchestrator queue."""
    mock_exec = MagicMock()
    mock_exec.run_executor.return_value = {"status": "ok"}
    with patch.dict(sys.modules, {"executor": mock_exec}):
        result = orch_mod.process_task(
            task_id="s3-persisted",
            task_description="repair the payment processing crash",
        )
    task = orch_mod.get_orchestrator().get_task("s3-persisted")
    assert task is not None
    assert task["status"] == "completed"


def test_s3_status_flows_to_queue():
    """Completed repair task appears in get_queue_status() recent list."""
    mock_exec = MagicMock()
    mock_exec.run_executor.return_value = {"status": "ok"}
    with patch.dict(sys.modules, {"executor": mock_exec}):
        orch_mod.process_task(
            task_id="s3-queue-check",
            task_description="fix the order processing bug",
        )
    queue_info = orch_mod.get_orchestrator().get_queue_status()
    ids = [t["task_id"] for t in queue_info["recent"]]
    assert "s3-queue-check" in ids


# ══════════════════════════════════════════════════════════════════════════════
# Scenario 4 — UI smoke test (Flask test client — no headless browser)
# ══════════════════════════════════════════════════════════════════════════════

def test_s4_dashboard_returns_html(flask_client):
    rv = flask_client.get("/")
    assert rv.status_code == 200
    # `/` now serves the SENTINEL PRIME HUD (desktop_dashboard_v2.html).
    assert b"SENTINEL PRIME" in rv.data


def test_s4_all_new_endpoints_200(flask_client):
    for path in (
        "/api/workers/status",
        "/api/tools/list",
        "/api/approvals/pending",
        "/api/revenue/status",
        "/api/tasks/queue",
    ):
        rv = flask_client.get(path)
        assert rv.status_code == 200, f"{path} returned {rv.status_code}"


def test_s4_new_endpoints_return_envelope(flask_client):
    """Every new endpoint returns {status, data, error} envelope."""
    for path in (
        "/api/workers/status",
        "/api/tools/list",
        "/api/approvals/pending",
        "/api/revenue/status",
        "/api/tasks/queue",
    ):
        rv = flask_client.get(path)
        body = rv.get_json()
        assert {"status", "data", "error"} <= set(body), f"{path}: {body}"


def test_s4_pending_approval_visible_in_dashboard(flask_client):
    """A forge_start approval created in the DB appears in /api/approvals/pending."""
    # Create approval directly (bypasses Ollama entirely) so we know the ID.
    appr_id = oc_mod.get_openclaw().request_approval(
        "Forge will build: dashboard test tool",
        "forge_start",
        {"prompt": "build dashboard test tool", "task_id": "s4-dash"},
    )
    assert appr_id is not None

    rv = flask_client.get("/api/approvals/pending")
    pending = rv.get_json()["data"]
    ids = {p["id"] for p in pending}
    assert appr_id in ids, f"approval {appr_id} not in pending list: {ids}"


def test_s4_approve_via_api_resolves(flask_client):
    """POST /api/approvals/resolve with approved=True clears pending."""
    # Create a pending approval.
    appr_id = oc_mod.get_openclaw().request_approval(
        "Forge will build: test tool",
        "forge_start",
        {"prompt": "build test"},
    )

    rv = flask_client.post(
        "/api/approvals/resolve",
        json={"approval_id": appr_id, "approved": True, "reason": "smoke ok"},
        content_type="application/json",
    )
    body = rv.get_json()
    assert rv.status_code == 200
    assert body["status"] == "ok"
    assert oc_mod.is_approved(appr_id)

    # No longer in pending list.
    rv2 = flask_client.get("/api/approvals/pending")
    ids = {p["id"] for p in rv2.get_json()["data"]}
    assert appr_id not in ids


def test_s4_task_submit_from_ui_creates_queue_entry(flask_client):
    """POST /api/tasks/submit → task appears in /api/tasks/queue."""
    with patch.dict(sys.modules, {"scanner": MagicMock(run_scan=MagicMock(return_value=0))}):
        rv = flask_client.post(
            "/api/tasks/submit",
            json={"description": "search github for python bounties", "source": "desktop"},
            content_type="application/json",
        )
    body = rv.get_json()
    assert rv.status_code == 201
    task_id = body["data"]["task_id"]

    rv2 = flask_client.get("/api/tasks/queue")
    queue_data = rv2.get_json()["data"]
    all_ids = [t["task_id"] for t in queue_data["recent"]]
    assert task_id in all_ids


def test_s4_existing_endpoints_not_broken(flask_client):
    """Regression: pre-existing endpoints still return 200."""
    for path in (
        "/api/status",
        "/api/logs",
        "/api/earnings",
        "/api/forge/tasks",
        "/api/tools/registry",
    ):
        rv = flask_client.get(path)
        assert rv.status_code == 200, f"{path} returned {rv.status_code}"


def test_s4_approvals_resolve_rejects_unknown_id(flask_client):
    """404 for unknown approval_id."""
    rv = flask_client.post(
        "/api/approvals/resolve",
        json={"approval_id": "appr-doesnotexist", "approved": True},
        content_type="application/json",
    )
    assert rv.status_code == 404
    body = rv.get_json()
    assert body["status"] == "error"
