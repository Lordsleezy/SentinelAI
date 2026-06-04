"""Repair memory — learned failure signatures and successful repair actions."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[3]
_DB_PATH = _ROOT / "data" / "sentinelvision" / "repair_memory.db"
_lock = threading.Lock()

_SEED_PATTERNS = [
    ("supabase", "policy already exists", "schema_failure", "DROP POLICY IF EXISTS {name} ON {table};", 0.85),
    ("supabase", "relation does not exist", "schema_failure", "CREATE TABLE or run migration for missing relation", 0.75),
    ("netlify", "missing env", "missing_environment_variable", "netlify env:set KEY value or UI env var", 0.9),
    ("netlify", "environment variable", "missing_environment_variable", "Create required env in Netlify site settings", 0.88),
    ("stripe", "webhook", "provider_failure", "stripe listen or Dashboard → Webhooks → Add endpoint", 0.8),
    ("stripe", "no such price", "provider_failure", "Create product/price in Stripe Dashboard or API", 0.7),
    ("cloudflare", "dns", "provider_failure", "Add DNS A/CNAME record in zone", 0.75),
    ("github", "repository not found", "auth_failure", "Create repo or fix GITHUB_TOKEN scope", 0.8),
    ("browser", "playwright", "missing_dependency", "pip install playwright && playwright install chromium", 0.95),
    ("auth", "401", "auth_failure", "Refresh vault credentials for provider", 0.85),
]


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    with _lock:
        conn = _connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS repair_patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    provider TEXT NOT NULL,
                    failure_signature TEXT NOT NULL,
                    root_cause TEXT NOT NULL,
                    repair_action TEXT NOT NULL,
                    success_count INTEGER DEFAULT 0,
                    fail_count INTEGER DEFAULT 0,
                    success_rate REAL DEFAULT 0.0,
                    last_used TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_repair_lookup
                    ON repair_patterns(provider, failure_signature);
            """)
            conn.commit()
            for row in _SEED_PATTERNS:
                exists = conn.execute(
                    "SELECT 1 FROM repair_patterns WHERE provider=? AND failure_signature LIKE ?",
                    (row[0], f"%{row[1][:40]}%"),
                ).fetchone()
                if not exists:
                    conn.execute(
                        """INSERT INTO repair_patterns
                           (provider, failure_signature, root_cause, repair_action, success_rate)
                           VALUES (?, ?, ?, ?, ?)""",
                        (row[0], row[1], row[2], row[3], row[4]),
                    )
            conn.commit()
        finally:
            conn.close()


class RepairMemoryStore:
    def __init__(self) -> None:
        _init_db()

    def find_repair(
        self,
        provider_id: str,
        failure_signature: str,
        failure_class: str,
    ) -> Optional[Dict[str, Any]]:
        with _lock:
            conn = _connect()
            try:
                rows = conn.execute(
                    """SELECT * FROM repair_patterns
                       WHERE provider IN (?, 'general', 'browser', 'auth')
                       ORDER BY success_rate DESC LIMIT 20""",
                    (provider_id,),
                ).fetchall()
            finally:
                conn.close()

        sig_lower = failure_signature.lower()
        class_lower = failure_class.lower()
        best = None
        best_score = 0.0
        for row in rows:
            pat = (row["failure_signature"] or "").lower()
            score = 0.0
            if pat in sig_lower or sig_lower in pat:
                score += 0.6
            if (row["root_cause"] or "").lower() in class_lower:
                score += 0.3
            score += float(row["success_rate"] or 0) * 0.2
            if score > best_score:
                best_score = score
                best = dict(row)
        return best if best_score >= 0.45 else None

    def record_outcome(
        self,
        provider_id: str,
        failure_signature: str,
        root_cause: str,
        repair_action: str,
        success: bool,
    ) -> None:
        with _lock:
            conn = _connect()
            try:
                row = conn.execute(
                    """SELECT id, success_count, fail_count FROM repair_patterns
                       WHERE provider=? AND failure_signature=? AND repair_action=?""",
                    (provider_id, failure_signature[:200], repair_action[:500]),
                ).fetchone()
                from core.sentinelvision.types import utc_now
                now = utc_now()
                if row:
                    sc = row["success_count"] + (1 if success else 0)
                    fc = row["fail_count"] + (0 if success else 1)
                    rate = sc / max(1, sc + fc)
                    conn.execute(
                        """UPDATE repair_patterns SET success_count=?, fail_count=?,
                           success_rate=?, last_used=? WHERE id=?""",
                        (sc, fc, rate, now, row["id"]),
                    )
                else:
                    conn.execute(
                        """INSERT INTO repair_patterns
                           (provider, failure_signature, root_cause, repair_action,
                            success_count, fail_count, success_rate, last_used)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            provider_id, failure_signature[:200], root_cause,
                            repair_action[:500],
                            1 if success else 0, 0 if success else 1,
                            1.0 if success else 0.0, now,
                        ),
                    )
                conn.commit()
            finally:
                conn.close()

    def list_top(self, limit: int = 20) -> List[Dict[str, Any]]:
        with _lock:
            conn = _connect()
            try:
                rows = conn.execute(
                    """SELECT provider, failure_signature, root_cause, repair_action,
                              success_rate, success_count, fail_count
                       FROM repair_patterns ORDER BY success_rate DESC, success_count DESC
                       LIMIT ?""",
                    (limit,),
                ).fetchall()
            finally:
                conn.close()
        return [dict(r) for r in rows]
