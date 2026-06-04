"""Autonomy score metrics — track phase success rates."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict

_ROOT = Path(__file__).resolve().parents[3]
_DB_PATH = _ROOT / "data" / "sentinelvision" / "autonomy_metrics.db"
_lock = threading.Lock()


def _connect():
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init():
    with _lock:
        conn = _connect()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phase TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    provider TEXT,
                    goal_id TEXT,
                    ts TEXT
                )
            """)
            conn.commit()
        finally:
            conn.close()


class AutonomyMetrics:
    def __init__(self) -> None:
        _init()

    def record(self, phase: str, success: bool, *, provider: str = "", goal_id: str = "") -> None:
        from core.sentinelvision.types import utc_now
        with _lock:
            conn = _connect()
            try:
                conn.execute(
                    "INSERT INTO metrics (phase, success, provider, goal_id, ts) VALUES (?, ?, ?, ?, ?)",
                    (phase, 1 if success else 0, provider, goal_id, utc_now()),
                )
                conn.commit()
            finally:
                conn.close()

    def _rate(self, phase: str) -> float:
        with _lock:
            conn = _connect()
            try:
                row = conn.execute(
                    "SELECT SUM(success) as s, COUNT(*) as c FROM metrics WHERE phase = ?",
                    (phase,),
                ).fetchone()
            finally:
                conn.close()
        if not row or not row["c"]:
            return 0.0
        return round(100.0 * (row["s"] or 0) / row["c"], 1)

    def summary(self) -> Dict[str, Any]:
        phases = ("research", "plan", "execute", "verify", "repair", "complete")
        rates = {p: self._rate(p) for p in phases}
        weights = {"research": 0.15, "plan": 0.1, "execute": 0.3, "verify": 0.25, "repair": 0.1, "complete": 0.1}
        score = sum(rates.get(p, 0) * weights.get(p, 0) for p in phases)
        return {
            "autonomy_score": round(score, 1),
            "research_success_pct": rates.get("research", 0),
            "plan_success_pct": rates.get("plan", 0),
            "execute_success_pct": rates.get("execute", 0),
            "verify_success_pct": rates.get("verify", 0),
            "repair_success_pct": rates.get("repair", 0),
            "completion_pct": rates.get("complete", 0),
            "provider_success_pct": self._rate("execute"),
            "goal": "95%+ autonomous completion",
        }
