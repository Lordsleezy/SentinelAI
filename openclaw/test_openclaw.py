"""Tests for openclaw.openclaw.

Run with: python -m pytest openclaw/test_openclaw.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class _OpenClawTestBase(unittest.TestCase):
    """Common setUp: point db at a temp file and reload modules."""

    @classmethod
    def setUpClass(cls):
        cls._tempdir = tempfile.mkdtemp(prefix="openclaw-test-")
        cls._db_path = os.path.join(cls._tempdir, "test.db")

        # Reload db so it picks up our patched DB_PATH.
        import importlib

        import db as _db
        importlib.reload(_db)
        _db.DB_PATH = cls._db_path
        _db.init_db()
        cls.db = _db

        # Reload openclaw so its singleton is fresh against our temp db.
        import openclaw.openclaw as _oc
        importlib.reload(_oc)
        _oc._instance = None
        _oc._schema_initialized = False
        _oc.ensure_approvals_table()
        cls.oc_module = _oc

    @classmethod
    def tearDownClass(cls):
        import shutil
        try:
            shutil.rmtree(cls._tempdir, ignore_errors=True)
        except Exception:
            pass

    def setUp(self):
        # Wipe the approvals table between tests.
        with self.db.get_conn() as conn:
            conn.execute("DELETE FROM approvals")
        # Fresh singleton.
        self.oc_module._instance = None
        self.openclaw = self.oc_module.get_openclaw()


class TestReceiveMessage(_OpenClawTestBase):
    def test_routes_to_orchestrator(self):
        fake_orch = MagicMock()
        fake_orch.process_task.return_value = {"intent": "search", "tool": "web"}
        self.openclaw.set_orchestrator(fake_orch)

        response = self.openclaw.receive_message(
            "desktop", "search github for python repos", {"task_id": "t-1"}
        )
        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["data"], {"intent": "search", "tool": "web"})
        fake_orch.process_task.assert_called_once()
        call_kwargs = fake_orch.process_task.call_args.kwargs
        self.assertEqual(call_kwargs["task_description"], "search github for python repos")
        self.assertEqual(call_kwargs["source"], "desktop")
        self.assertEqual(call_kwargs["task_id"], "t-1")

    def test_invalid_source(self):
        response = self.openclaw.receive_message("smoke-signal", "hi")
        self.assertEqual(response["status"], "error")
        self.assertIn("invalid source", response["error"])

    def test_empty_message_rejected(self):
        response = self.openclaw.receive_message("desktop", "  ")
        self.assertEqual(response["status"], "error")

    def test_no_orchestrator_returns_queued(self):
        self.openclaw.set_orchestrator(None)
        response = self.openclaw.receive_message("api", "ping")
        self.assertEqual(response["status"], "queued")

    def test_orchestrator_exception_caught(self):
        fake_orch = MagicMock()
        fake_orch.process_task.side_effect = RuntimeError("boom")
        self.openclaw.set_orchestrator(fake_orch)

        response = self.openclaw.receive_message("desktop", "do thing")
        self.assertEqual(response["status"], "error")
        self.assertIn("boom", response["error"])


class TestRequestApproval(_OpenClawTestBase):
    def test_creates_pending_record(self):
        approval_id = self.openclaw.request_approval(
            "Forge will build: PDF extractor",
            "forge_start",
            {"prompt": "build a pdf extractor"},
        )
        self.assertTrue(approval_id.startswith("appr-"))

        approval = self.openclaw.get_approval(approval_id)
        self.assertIsNotNone(approval)
        self.assertEqual(approval["status"], "pending")
        self.assertEqual(approval["action_type"], "forge_start")
        self.assertEqual(approval["payload"], {"prompt": "build a pdf extractor"})

    def test_invalid_action_type_rejected(self):
        with self.assertRaises(ValueError):
            self.openclaw.request_approval("does X", "launch_missiles", {})

    def test_duplicate_pending_returns_existing_id(self):
        payload = {"prompt": "build x", "version": 1}
        first = self.openclaw.request_approval("build x", "forge_start", payload)
        second = self.openclaw.request_approval("build x AGAIN", "forge_start", payload)
        self.assertEqual(first, second)
        # And there must still be exactly one pending row.
        pending = self.openclaw.get_pending_approvals()
        self.assertEqual(len(pending), 1)

    def test_different_payloads_create_separate_approvals(self):
        a = self.openclaw.request_approval("build x", "forge_start", {"prompt": "x"})
        b = self.openclaw.request_approval("build y", "forge_start", {"prompt": "y"})
        self.assertNotEqual(a, b)


class TestResolveApproval(_OpenClawTestBase):
    def test_resolve_marks_approved(self):
        approval_id = self.openclaw.request_approval("do thing", "forge_start", {"k": 1})
        ok = self.openclaw.resolve_approval(approval_id, approved=True, reason="lgtm")
        self.assertTrue(ok)

        approval = self.openclaw.get_approval(approval_id)
        self.assertEqual(approval["status"], "approved")
        self.assertEqual(approval["reason"], "lgtm")
        self.assertIsNotNone(approval["resolved_at"])
        self.assertTrue(self.openclaw.is_approved(approval_id))

    def test_resolve_marks_denied(self):
        approval_id = self.openclaw.request_approval("do thing", "forge_start", {"k": 2})
        self.openclaw.resolve_approval(approval_id, approved=False, reason="nope")
        self.assertFalse(self.openclaw.is_approved(approval_id))
        approval = self.openclaw.get_approval(approval_id)
        self.assertEqual(approval["status"], "denied")

    def test_unknown_approval_id_raises(self):
        with self.assertRaises(self.oc_module.ApprovalNotFoundError):
            self.openclaw.resolve_approval("appr-doesnotexist", approved=True)

    def test_already_resolved_is_noop(self):
        approval_id = self.openclaw.request_approval("do thing", "forge_start", {"k": 3})
        self.openclaw.resolve_approval(approval_id, approved=True)
        # Trying to flip should be a no-op (False) without raising.
        ok = self.openclaw.resolve_approval(approval_id, approved=False)
        self.assertFalse(ok)
        # Status stays at first decision.
        approval = self.openclaw.get_approval(approval_id)
        self.assertEqual(approval["status"], "approved")


class TestForgeApprovalGate(_OpenClawTestBase):
    """The hard rule — Forge cannot start without an approved DB record."""

    def test_forge_blocked_without_approval(self):
        # The orchestrator (and any caller) MUST refuse to launch Forge unless
        # is_approved() returns True. We simulate that check here.
        approval_id = self.openclaw.request_approval(
            "Forge will build: pdf scraper",
            "forge_start",
            {"prompt": "build a pdf scraper"},
        )
        self.assertFalse(self.openclaw.is_approved(approval_id))

        forge_ran = []

        def launch_forge_if_approved(aid):
            if not self.openclaw.is_approved(aid):
                return "blocked"
            forge_ran.append(aid)
            return "ran"

        self.assertEqual(launch_forge_if_approved(approval_id), "blocked")
        self.assertEqual(forge_ran, [])

        # User approves.
        self.openclaw.resolve_approval(approval_id, approved=True)
        self.assertEqual(launch_forge_if_approved(approval_id), "ran")
        self.assertEqual(forge_ran, [approval_id])

    def test_pending_approval_blocks_duplicate_for_same_action(self):
        payload = {"prompt": "build pdf extractor"}
        first = self.openclaw.request_approval(
            "Forge will build: pdf extractor", "forge_start", payload
        )
        # Second request with same payload should return the same id, not
        # create a new row.
        second = self.openclaw.request_approval(
            "Forge will build: pdf extractor (retry)", "forge_start", payload
        )
        self.assertEqual(first, second)


class TestPendingApprovalsList(_OpenClawTestBase):
    def test_list_only_returns_pending(self):
        a = self.openclaw.request_approval("a", "forge_start", {"k": "a"})
        b = self.openclaw.request_approval("b", "forge_start", {"k": "b"})
        c = self.openclaw.request_approval("c", "forge_start", {"k": "c"})

        self.openclaw.resolve_approval(b, approved=True)
        self.openclaw.resolve_approval(c, approved=False)

        pending = self.openclaw.get_pending_approvals()
        ids = {p["id"] for p in pending}
        self.assertEqual(ids, {a})


class TestSendNotification(_OpenClawTestBase):
    def test_returns_notification_id(self):
        notif_id = self.openclaw.send_notification("hello", priority="normal")
        self.assertTrue(notif_id.startswith("notif-"))

    def test_unknown_priority_defaults_to_normal(self):
        # Must not raise.
        notif_id = self.openclaw.send_notification("hi", priority="ULTRA")
        self.assertTrue(notif_id.startswith("notif-"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
