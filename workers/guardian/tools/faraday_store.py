"""
FaradayStore — local SQLite-based vulnerability findings store.
Simplified Faraday-compatible schema. Full Faraday integration in v2.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent.parent.parent / "memory" / "guardian_findings.db"


class FaradayStore:
    """
    Stores Guardian vulnerability findings in a local SQLite database.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = Path(db_path or DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS findings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    template TEXT,
                    severity TEXT,
                    target TEXT,
                    description TEXT,
                    reference TEXT,
                    source TEXT DEFAULT 'guardian',
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_session ON findings(session_id)
            """)
            conn.commit()

    def save_finding(self, finding: Any, session_id: str) -> int:
        """Save a vulnerability finding (accepts Finding dataclass or dict)."""
        if hasattr(finding, "to_dict"):
            data = finding.to_dict()
        elif isinstance(finding, dict):
            data = finding
        else:
            data = {"description": str(finding)}

        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO findings
                    (session_id, template, severity, target, description, reference, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    data.get("template", ""),
                    data.get("severity", "unknown"),
                    data.get("target", ""),
                    data.get("description", ""),
                    json.dumps(data.get("reference", [])),
                    data.get("source", "guardian"),
                    datetime.now().isoformat(),
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_findings(self, session_id: Optional[str] = None) -> List[dict]:
        """Get all findings, optionally filtered by session."""
        with self._connect() as conn:
            if session_id:
                rows = conn.execute(
                    "SELECT * FROM findings WHERE session_id = ? ORDER BY created_at DESC",
                    (session_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM findings ORDER BY created_at DESC"
                ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            try:
                d["reference"] = json.loads(d.get("reference", "[]"))
            except Exception:
                d["reference"] = []
            result.append(d)
        return result

    def export_report(self, session_id: str, format: str = "md") -> str:
        """Export findings as markdown or JSON report."""
        findings = self.get_findings(session_id)
        if not findings:
            return f"# Guardian Report — {session_id}\n\nNo findings recorded.\n"

        if format == "json":
            return json.dumps({"session_id": session_id, "findings": findings}, indent=2)

        # Markdown format
        lines = [
            f"# Guardian Security Report",
            f"**Session:** {session_id}",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            f"**Total Findings:** {len(findings)}",
            "",
            "---",
            "",
        ]
        by_severity = {}
        for f in findings:
            sev = f.get("severity", "unknown").upper()
            by_severity.setdefault(sev, []).append(f)

        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"]:
            if sev not in by_severity:
                continue
            lines.append(f"## {sev} ({len(by_severity[sev])})")
            lines.append("")
            for finding in by_severity[sev]:
                lines.append(f"### {finding.get('template', 'Finding')}")
                lines.append(f"- **Target:** `{finding.get('target', 'N/A')}`")
                lines.append(f"- **Description:** {finding.get('description', 'N/A')}")
                refs = finding.get("reference", [])
                if refs:
                    lines.append(f"- **References:** {', '.join(refs[:3])}")
                lines.append("")

        return "\n".join(lines)

    def clear_session(self, session_id: str) -> int:
        """Delete all findings for a session. Returns count deleted."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM findings WHERE session_id = ?", (session_id,)
            )
            conn.commit()
            return cursor.rowcount
