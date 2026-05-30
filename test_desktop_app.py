"""Tests for new desktop_app.py endpoints.

Run with: python -m pytest test_desktop_app.py -v
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _make_test_db():
    td = tempfile.mkdtemp(prefix="deskapp-test-")
    db_path = os.path.join(td, "test.db")

    import importlib
    import db as _db
    importlib.reload(_db)
    _db.DB_PATH = db_path
    _db.init_db()
    return td, db_path, _db


class TestDesktopAppEndpoints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tempdir, cls._db_path, cls.db = _make_test_db()

        # Patch Ollama
        cls._ollama_patch = patch("orchestrator._ollama_available", return_value=False)
        cls._ollama_patch.start()

        # Reload openclaw singleton
        import openclaw.openclaw as _oc
        importlib.reload(_oc)
        _oc._instance = None
        _oc._schema_initialized = False
        _oc.ensure_approvals_table()

        # Reload orchestrator singleton
        import orchestrator as _orch
        importlib.reload(_orch)
        _orch._orchestrator = None
        _orch._schema_initialized = False
        _orch.ensure_orchestrator_table()

        # Stub out heavy imports that desktop_app.py pulls in at module level.
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
        # internet_runtime needs get_research_runtime
        stubs["internet_runtime"].get_research_runtime = MagicMock(return_value=MagicMock())
        stubs["memory.filesystem_index"].get_filesystem_indexer = MagicMock(return_value=MagicMock())
        stubs["memory.persistent_memory"].get_memory = MagicMock(return_value=MagicMock())
        stubs["model_router"].get_model_router = MagicMock(return_value=MagicMock())
        stubs["reflection"].ReflectionEngine = MagicMock()
        stubs["tool_registry"].get_tool_registry = MagicMock(return_value=MagicMock())

        for mod, stub in stubs.items():
            sys.modules.setdefault(mod, stub)

        # Now we can import desktop_app safely.
        import desktop_app as _da
        importlib.reload(_da)
        cls.da = _da
        cls.app = _da.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls._ollama_patch.stop()
        import shutil
        try:
            shutil.rmtree(cls._tempdir, ignore_errors=True)
        except Exception:
            pass

    def setUp(self):
        # Wipe approval + orchestrator tables before each test.
        with self.db.get_conn() as conn:
            conn.execute("DELETE FROM approvals")
        import orchestrator as _orch
        with self.db.get_conn() as conn:
            conn.execute("DELETE FROM orchestrator_tasks")
        import openclaw.openclaw as _oc
        _oc._instance = None
        _oc._schema_initialized = False
        _oc.ensure_approvals_table()
        _orch._orchestrator = None
        _orch._schema_initialized = False
        _orch.ensure_orchestrator_table()

    # ── envelope helpers ─────────────────────────────────────────────────

    def _get(self, path):
        rv = self.app.get(path)
        data = json.loads(rv.data)
        return rv, data

    def _post(self, path, payload=None):
        rv = self.app.post(
            path,
            json=payload or {},
            content_type="application/json",
        )
        data = json.loads(rv.data)
        return rv, data

    # ── /api/workers/status ──────────────────────────────────────────────

    def test_workers_status_returns_envelope(self):
        rv, body = self._get("/api/workers/status")
        self.assertEqual(rv.status_code, 200)
        self.assertEqual(body["status"], "ok")
        self.assertIn("data", body)
        self.assertIn("error", body)
        self.assertIsNone(body["error"])

    # ── /api/tools/registry ──────────────────────────────────────────────

    def test_tools_registry_returns_list(self):
        rv, body = self._get("/api/tools/registry")
        self.assertEqual(rv.status_code, 200)
        self.assertIn("tools", body)

    def test_tools_list_envelope(self):
        rv, body = self._get("/api/tools/list")
        self.assertEqual(rv.status_code, 200)
        self.assertEqual(body["status"], "ok")
        self.assertIsInstance(body["data"], list)

    # ── /api/tools/find ──────────────────────────────────────────────────

    def test_tools_find_requires_task(self):
        rv, body = self._post("/api/tools/find", {})
        self.assertEqual(rv.status_code, 400)

    def test_tools_find_returns_tool_key(self):
        rv, body = self._post("/api/tools/find", {"task": "search for bounties"})
        self.assertEqual(rv.status_code, 200)
        self.assertIn("tool", body)

    # ── /api/approvals/pending ───────────────────────────────────────────

    def test_approvals_pending_empty(self):
        rv, body = self._get("/api/approvals/pending")
        self.assertEqual(rv.status_code, 200)
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["data"], [])

    def test_approvals_pending_shows_forge_gate(self):
        # Submit a build task → creates approval.
        self._post("/api/tasks/submit", {
            "description": "build a PDF parser",
            "source": "desktop",
            "context": {"wait_for_approval": False},
        })
        rv, body = self._get("/api/approvals/pending")
        self.assertEqual(body["status"], "ok")
        self.assertGreaterEqual(len(body["data"]), 1)
        self.assertEqual(body["data"][0]["action_type"], "forge_start")

    # ── /api/approvals/resolve ───────────────────────────────────────────

    def test_approvals_resolve_rejects_unknown_id(self):
        rv, body = self._post("/api/approvals/resolve", {
            "approval_id": "appr-doesnotexist",
            "approved": True,
        })
        self.assertEqual(rv.status_code, 404)
        self.assertEqual(body["status"], "error")

    def test_approvals_resolve_approves_correctly(self):
        # Create a pending approval.
        from openclaw.openclaw import get_openclaw
        appr_id = get_openclaw().request_approval(
            "Forge will build: test thing",
            "forge_start",
            {"prompt": "test"},
        )
        rv, body = self._post("/api/approvals/resolve", {
            "approval_id": appr_id,
            "approved": True,
            "reason": "looks good",
        })
        self.assertEqual(rv.status_code, 200)
        self.assertEqual(body["status"], "ok")
        self.assertTrue(body["data"]["resolved"])
        # Verify in DB.
        approval = get_openclaw().get_approval(appr_id)
        self.assertEqual(approval["status"], "approved")

    def test_approvals_resolve_requires_approval_id(self):
        rv, body = self._post("/api/approvals/resolve", {"approved": True})
        self.assertEqual(rv.status_code, 400)

    # ── /api/revenue/status ──────────────────────────────────────────────

    def test_revenue_status_envelope(self):
        rv, body = self._get("/api/revenue/status")
        self.assertEqual(rv.status_code, 200)
        self.assertEqual(body["status"], "ok")
        self.assertIn("earnings", body["data"])

    # ── /api/tasks/submit ────────────────────────────────────────────────

    def test_tasks_submit_creates_queue_entry(self):
        rv, body = self._post("/api/tasks/submit", {
            "description": "search for python bounties on github",
            "source": "desktop",
        })
        self.assertEqual(rv.status_code, 201)
        self.assertEqual(body["status"], "ok")
        task_id = body["data"]["task_id"]
        self.assertIsNotNone(task_id)
        # Verify persisted.
        import orchestrator as _orch
        task = _orch.get_orchestrator().get_task(task_id)
        self.assertIsNotNone(task)

    def test_tasks_submit_requires_description(self):
        rv, body = self._post("/api/tasks/submit", {"source": "desktop"})
        self.assertEqual(rv.status_code, 400)
        self.assertEqual(body["status"], "error")

    def test_tasks_submit_build_creates_approval(self):
        rv, body = self._post("/api/tasks/submit", {
            "description": "build a JSON diffing tool",
            "source": "api",
            "context": {"wait_for_approval": False},
        })
        self.assertEqual(rv.status_code, 201)
        self.assertIsNotNone(body["data"].get("approval_id"))

    # ── /api/tasks/queue ─────────────────────────────────────────────────

    def test_tasks_queue_envelope(self):
        rv, body = self._get("/api/tasks/queue")
        self.assertEqual(rv.status_code, 200)
        self.assertEqual(body["status"], "ok")
        self.assertIn("counts", body["data"])
        self.assertIn("recent", body["data"])

    # ── regression: existing endpoints still work ────────────────────────

    def test_existing_api_status_still_works(self):
        rv = self.app.get("/api/status")
        self.assertEqual(rv.status_code, 200)
        body = json.loads(rv.data)
        self.assertIn("running", body)

    def test_existing_api_logs_still_works(self):
        rv = self.app.get("/api/logs")
        self.assertEqual(rv.status_code, 200)
        body = json.loads(rv.data)
        self.assertIn("logs", body)

    def test_existing_api_earnings_still_works(self):
        rv = self.app.get("/api/earnings")
        self.assertEqual(rv.status_code, 200)
        body = json.loads(rv.data)
        self.assertIn("confirmed_earnings", body)

    def test_existing_api_forge_tasks_still_works(self):
        rv = self.app.get("/api/forge/tasks")
        self.assertEqual(rv.status_code, 200)
        body = json.loads(rv.data)
        self.assertIn("tasks", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
