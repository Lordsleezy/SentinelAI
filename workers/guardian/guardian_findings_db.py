"""
Guardian Findings DB — searchable, filterable, exportable findings store.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).resolve().parents[2] / "memory" / "guardian_findings_v3.db"


class GuardianFindingsDB:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = Path(db_path or DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS findings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    severity TEXT,
                    evidence TEXT,
                    description TEXT,
                    status TEXT DEFAULT 'open',
                    session_id TEXT,
                    report_path TEXT,
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_target ON findings(target)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_severity ON findings(severity)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON findings(session_id)")
            conn.commit()

    def add(
        self,
        *,
        target: str,
        tool: str,
        severity: str = "informational",
        evidence: str = "",
        description: str = "",
        status: str = "open",
        session_id: str = "",
        report_path: str = "",
    ) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO findings
                   (target, tool, severity, evidence, description, status, session_id, report_path, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    target, tool, severity, evidence[:8000], description[:4000],
                    status, session_id, report_path, datetime.now().isoformat(),
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def add_from_nuclei(self, finding: Any, target: str, session_id: str) -> int:
        if hasattr(finding, "to_dict"):
            d = finding.to_dict()
        elif isinstance(finding, dict):
            d = finding
        else:
            d = {"description": str(finding)}
        return self.add(
            target=target or d.get("target", ""),
            tool="nuclei",
            severity=(d.get("severity") or "unknown").lower(),
            evidence=d.get("template", ""),
            description=d.get("description", ""),
            session_id=session_id,
        )

    def search(
        self,
        *,
        target: Optional[str] = None,
        severity: Optional[str] = None,
        tool: Optional[str] = None,
        status: Optional[str] = None,
        session_id: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        q = "SELECT * FROM findings WHERE 1=1"
        params: List[Any] = []
        if target:
            q += " AND target LIKE ?"
            params.append(f"%{target}%")
        if severity:
            q += " AND LOWER(severity)=LOWER(?)"
            params.append(severity)
        if tool:
            q += " AND LOWER(tool)=LOWER(?)"
            params.append(tool)
        if status:
            q += " AND LOWER(status)=LOWER(?)"
            params.append(status)
        if session_id:
            q += " AND session_id=?"
            params.append(session_id)
        q += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def export_json(self, path: Path, **filters: Any) -> int:
        rows = self.search(**filters, limit=5000)
        path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        return len(rows)

    def export_csv(self, path: Path, **filters: Any) -> int:
        rows = self.search(**filters, limit=5000)
        if not rows:
            path.write_text("", encoding="utf-8")
            return 0
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=rows[0].keys())
            w.writeheader()
            w.writerows(rows)
        return len(rows)

    def count(self, session_id: Optional[str] = None) -> int:
        with self._connect() as conn:
            if session_id:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM findings WHERE session_id=?",
                    (session_id,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS c FROM findings").fetchone()
        return int(row["c"]) if row else 0
