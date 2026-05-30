"""Tests for orchestrator.py.

Run with: python -m pytest test_orchestrator.py -v
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class _OrchestratorTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tempdir = tempfile.mkdtemp(prefix="orch-test-")
        cls._db_path = os.path.join(cls._tempdir, "test.db")

        import importlib
        import db as _db
        importlib.reload(_db)
        _db.DB_PATH = cls._db_path
        _db.init_db()
        cls.db = _db

        # Reload modules BEFORE patching so the reload doesn't clobber our mock.
        import openclaw.openclaw as _oc
        importlib.reload(_oc)
        _oc._instance = None
        _oc._schema_initialized = False
        _oc.ensure_approvals_table()

        import orchestrator as _orch
        importlib.reload(_orch)
        _orch._orchestrator = None
        _orch._schema_initialized = False
        _orch.ensure_orchestrator_table()
        cls.orch_module = _orch

        # Patch Ollama AFTER reload so the reload doesn't restore the real fn.
        cls._ollama_patcher = patch("orchestrator._ollama_available", return_value=False)
        cls._ollama_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls._ollama_patcher.stop()
        import shutil
        try:
            shutil.rmtree(cls._tempdir, ignore_errors=True)
        except Exception:
            pass

    def setUp(self):
        # Fresh tables.
        with self.db.get_conn() as conn:
            conn.execute("DELETE FROM orchestrator_tasks")
            conn.execute("DELETE FROM approvals")
        # Fresh singleton.
        self.orch_module._orchestrator = None
        self.orch_module._schema_initialized = False
        import openclaw.openclaw as _oc
        _oc._instance = None
        _oc._schema_initialized = False
        _oc.ensure_approvals_table()
        self.orch_module.ensure_orchestrator_table()
        self.orch = self.orch_module.get_orchestrator()


class TestParseIntent(_OrchestratorTestBase):
    def test_repair_intent(self):
        info = self.orch_module.parse_intent("fix the crash in the payment module")
        self.assertEqual(info["intent"], "repair")

    def test_build_intent(self):
        info = self.orch_module.parse_intent("build a tool to parse PDFs")
        self.assertEqual(info["intent"], "build")

    def test_search_intent(self):
        info = self.orch_module.parse_intent("search GitHub for Python repos with bounties")
        self.assertEqual(info["intent"], "search")

    def test_monitor_intent(self):
        info = self.orch_module.parse_intent("monitor system health")
        self.assertEqual(info["intent"], "monitor")

    def test_unknown_intent(self):
        info = self.orch_module.parse_intent("xyzzy frobnicator quux")
        self.assertEqual(info["intent"], "unknown")

    def test_empty_text_unknown(self):
        info = self.orch_module.parse_intent("")
        self.assertEqual(info["intent"], "unknown")


class TestRepairIntentRouting(_OrchestratorTestBase):
    def test_repair_routes_to_repair_worker(self):
        # Patch executor.run_executor to avoid real I/O.
        mock_executor = MagicMock()
        mock_executor.run_executor.return_value = {"status": "dry_run_ok"}
        with patch.dict("sys.modules", {"executor": mock_executor}):
            result = self.orch.process_task(
                task_id="t-repair-1",
                task_description="fix the bug in the login flow",
                source="desktop",
            )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["worker"], "repair")
        self.assertIsNone(result.get("approval_id"))

    def test_search_routes_to_search_worker(self):
        with patch.dict("sys.modules", {"scanner": MagicMock(run_scan=MagicMock(return_value=0))}):
            result = self.orch.process_task(
                task_id="t-search-1",
                task_description="search github for python repos",
                source="api",
            )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["worker"], "search")


class TestBuildIntentForgeGate(_OrchestratorTestBase):
    def test_build_triggers_forge_approval(self):
        result = self.orch.process_task(
            task_id="t-build-1",
            task_description="build a PDF extractor tool",
            source="desktop",
            context={"wait_for_approval": False},
        )
        self.assertEqual(result["status"], "awaiting_approval")
        self.assertIsNotNone(result.get("approval_id"))
        self.assertTrue(result.get("needs_forge"))

        # DB should have a pending approval row.
        pending = self.orch.openclaw.get_pending_approvals()
        self.assertTrue(any(p["id"] == result["approval_id"] for p in pending))

    def test_forge_never_starts_without_approval(self):
        result = self.orch.process_task(
            task_id="t-build-nogrant",
            task_description="create a PDF parser",
            source="desktop",
            context={"wait_for_approval": False},
        )
        approval_id = result["approval_id"]

        # Should NOT be approved yet.
        self.assertFalse(self.orch.openclaw.is_approved(approval_id))

        # Calling _run_forge directly without approval must raise.
        with self.assertRaises(RuntimeError):
            self.orch._run_forge(
                task_id="t-build-nogrant",
                approval_id=approval_id,
                forge_prompt="build pdf parser",
                intent={},
            )

    def test_forge_runs_after_approval(self):
        result = self.orch.process_task(
            task_id="t-forge-ok",
            task_description="create a PDF parser tool",
            source="desktop",
            context={"wait_for_approval": False},
        )
        approval_id = result["approval_id"]
        self.orch.openclaw.resolve_approval(approval_id, approved=True)

        # Patch forge_worker.run_forge_task to avoid needing node + Forge.
        mock_fw = MagicMock()
        mock_fw.run_forge_task.return_value = {
            "output_path": "/fake/path",
            "summary": "built pdf parser",
        }
        with patch.dict("sys.modules", {"workers.forge_worker": mock_fw,
                                         "workers": MagicMock(forge_worker=mock_fw)}):
            resumed = self.orch.resume_approved_task("t-forge-ok")

        self.assertEqual(resumed["status"], "completed")
        self.assertIsNotNone(resumed.get("result", {}).get("registered_tool"))

    def test_build_intent_in_db_is_awaiting_approval(self):
        self.orch.process_task(
            task_id="t-build-db",
            task_description="build a CSV merger",
            source="desktop",
            context={"wait_for_approval": False},
        )
        task = self.orch.get_task("t-build-db")
        self.assertIsNotNone(task)
        self.assertEqual(task["status"], "awaiting_approval")
        self.assertIsNotNone(task["approval_id"])


class TestTaskQueuePersistence(_OrchestratorTestBase):
    def test_task_persists_and_is_readable(self):
        self.orch.process_task(
            task_id="t-persist-1",
            task_description="search github",
            source="desktop",
        )
        task = self.orch.get_task("t-persist-1")
        self.assertIsNotNone(task)
        self.assertEqual(task["status"], "completed")

    def test_pending_tasks_resume_on_restart(self):
        # Simulate an in-flight task that existed before a crash.
        with self.db.get_conn() as conn:
            conn.execute(
                """INSERT INTO orchestrator_tasks
                      (task_id, description, source, context_json, status,
                       created_at, updated_at)
                   VALUES ('t-crashed', 'build thing', 'desktop', '{}',
                           'running', datetime('now'), datetime('now'))"""
            )
        # After restart, recover_pending should mark it 'pending'.
        n = self.orch.recover_pending()
        self.assertGreaterEqual(n, 1)
        task = self.orch.get_task("t-crashed")
        self.assertEqual(task["status"], "pending")

    def test_queue_status_returns_counts(self):
        self.orch.process_task(
            task_id="t-qs-1",
            task_description="find github bounties",
            source="api",
        )
        qs = self.orch.get_queue_status()
        self.assertIn("counts", qs)
        self.assertIn("recent", qs)


class TestUnknownIntent(_OrchestratorTestBase):
    def test_unknown_intent_no_tool_returns_forge_or_graceful(self):
        result = self.orch.process_task(
            task_id="t-unknown",
            task_description="xyzzy quux frobnicator blergh",
            source="desktop",
            context={"wait_for_approval": False},
        )
        # Must never raise an exception. Status can be awaiting_approval
        # (needs forge) or completed (matched a tool). It must not be "error"
        # due to an unhandled exception.
        self.assertNotEqual(result.get("status"), "failed")
        self.assertIn(result["status"], ("completed", "awaiting_approval"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
