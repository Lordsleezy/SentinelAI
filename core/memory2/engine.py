"""Memory 2.0 — persistent multi-type memory with retrieval, consolidation, and health."""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sentinel.memory2")

_ROOT = Path(__file__).resolve().parents[2]
_DB_PATH = _ROOT / "data" / "memory2" / "memory.db"
_lock = threading.Lock()

MEMORY_TYPES = ("long_term", "project", "workflow", "repair", "preference")
DEFAULT_TTL_DAYS = {
    "long_term": 3650,
    "project": 365,
    "workflow": 180,
    "repair": 90,
    "preference": 3650,
}


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


class Memory2Engine:
    def __init__(self) -> None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._bridge_legacy()

    def _init_db(self) -> None:
        with _lock:
            conn = sqlite3.connect(str(_DB_PATH))
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS entries (
                        id TEXT PRIMARY KEY,
                        memory_type TEXT NOT NULL,
                        key TEXT,
                        content TEXT NOT NULL,
                        summary TEXT,
                        project_id TEXT,
                        source TEXT,
                        importance INTEGER DEFAULT 5,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        accessed_at TEXT,
                        metadata TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_mem_type ON entries(memory_type);
                    CREATE INDEX IF NOT EXISTS idx_mem_project ON entries(project_id);
                    CREATE INDEX IF NOT EXISTS idx_mem_key ON entries(key);
                    CREATE TABLE IF NOT EXISTS health_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        recorded_at TEXT NOT NULL,
                        metrics TEXT NOT NULL
                    );
                """)
                conn.commit()
            finally:
                conn.close()

    def _bridge_legacy(self) -> None:
        """Import existing repair / workflow stores once at startup."""
        try:
            from core.sentinelvision.self_correction.repair_memory import RepairMemoryStore
            store = RepairMemoryStore()
            for row in store.list_top(50):
                self.remember(
                    "repair",
                    json.dumps(row)[:4000],
                    key=(row.get("failure_signature") or row.get("provider", ""))[:120],
                    source="repair_memory.db",
                    importance=7,
                )
        except Exception as e:
            logger.debug("repair bridge: %s", e)
        try:
            wf = _ROOT / "data" / "sentinelvision" / "workflow_memory.json"
            if wf.is_file():
                data = json.loads(wf.read_text(encoding="utf-8"))
                for item in (data if isinstance(data, list) else data.get("workflows", []))[:30]:
                    self.remember(
                        "workflow",
                        json.dumps(item)[:4000],
                        key=(item.get("objective") or item.get("pattern", ""))[:120],
                        source="workflow_memory.json",
                    )
        except Exception as e:
            logger.debug("workflow bridge: %s", e)
        try:
            proj = _ROOT / "memory" / "vault" / "projects" / "projects.json"
            if proj.is_file():
                projects = json.loads(proj.read_text(encoding="utf-8"))
                for p in (projects if isinstance(projects, list) else projects.get("projects", []))[:50]:
                    self.remember(
                        "project",
                        json.dumps(p)[:4000],
                        key=p.get("id") or p.get("name", ""),
                        project_id=p.get("id"),
                        source="projects.json",
                    )
        except Exception as e:
            logger.debug("project bridge: %s", e)

    def remember(
        self,
        memory_type: str,
        content: str,
        *,
        key: Optional[str] = None,
        summary: Optional[str] = None,
        project_id: Optional[str] = None,
        source: str = "sentinel",
        importance: int = 5,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        if memory_type not in MEMORY_TYPES:
            raise ValueError(f"invalid memory_type: {memory_type}")
        entry_id = str(uuid.uuid4())
        now = _utc()
        with _lock:
            conn = sqlite3.connect(str(_DB_PATH))
            try:
                conn.execute(
                    """INSERT INTO entries
                       (id, memory_type, key, content, summary, project_id, source,
                        importance, created_at, updated_at, accessed_at, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        entry_id,
                        memory_type,
                        key or "",
                        content[:50000],
                        summary or "",
                        project_id or "",
                        source,
                        importance,
                        now,
                        now,
                        now,
                        json.dumps(metadata or {}),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        return entry_id

    def retrieve(
        self,
        query: str,
        *,
        memory_type: Optional[str] = None,
        project_id: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        q = f"%{query.lower()}%"
        sql = """SELECT * FROM entries WHERE (LOWER(content) LIKE ? OR LOWER(key) LIKE ?
                 OR LOWER(summary) LIKE ?)"""
        params: List[Any] = [q, q, q]
        if memory_type:
            sql += " AND memory_type = ?"
            params.append(memory_type)
        if project_id:
            sql += " AND project_id = ?"
            params.append(project_id)
        sql += " ORDER BY importance DESC, updated_at DESC LIMIT ?"
        params.append(limit)
        return self._fetch(sql, params)

    def get_by_type(self, memory_type: str, limit: int = 50) -> List[Dict[str, Any]]:
        return self._fetch(
            "SELECT * FROM entries WHERE memory_type = ? ORDER BY updated_at DESC LIMIT ?",
            (memory_type, limit),
        )

    def summarize(self, memory_type: Optional[str] = None, limit: int = 30) -> Dict[str, Any]:
        entries = self.get_by_type(memory_type, limit) if memory_type else self._fetch(
            "SELECT * FROM entries ORDER BY updated_at DESC LIMIT ?", (limit,)
        )
        bullets = []
        for e in entries[:limit]:
            text = (e.get("summary") or e.get("content", ""))[:200]
            bullets.append(f"- [{e['memory_type']}] {text}")
        return {
            "count": len(entries),
            "memory_type": memory_type,
            "summary": "\n".join(bullets) if bullets else "No memories stored.",
            "generated_at": _utc(),
        }

    def consolidate(self, memory_type: Optional[str] = None) -> Dict[str, Any]:
        """Merge duplicate keys within a type; keep highest importance."""
        merged = 0
        with _lock:
            conn = sqlite3.connect(str(_DB_PATH))
            conn.row_factory = sqlite3.Row
            try:
                types = [memory_type] if memory_type else list(MEMORY_TYPES)
                for mt in types:
                    rows = conn.execute(
                        "SELECT key, GROUP_CONCAT(id) as ids, COUNT(*) as c FROM entries "
                        "WHERE memory_type = ? AND key != '' GROUP BY key HAVING c > 1",
                        (mt,),
                    ).fetchall()
                    for row in rows:
                        ids = (row["ids"] or "").split(",")
                        keep, drop = ids[0], ids[1:]
                        for did in drop:
                            conn.execute("DELETE FROM entries WHERE id = ?", (did,))
                            merged += 1
                conn.commit()
            finally:
                conn.close()
        self._record_health()
        return {"ok": True, "merged_duplicates": merged}

    def cleanup(self, *, dry_run: bool = False) -> Dict[str, Any]:
        removed = 0
        now = datetime.now(timezone.utc)
        with _lock:
            conn = sqlite3.connect(str(_DB_PATH))
            conn.row_factory = sqlite3.Row
            try:
                for mt, days in DEFAULT_TTL_DAYS.items():
                    cutoff = (now - timedelta(days=days)).isoformat()
                    cur = conn.execute(
                        "SELECT id FROM entries WHERE memory_type = ? AND updated_at < ? AND importance < 8",
                        (mt, cutoff),
                    )
                    ids = [r["id"] for r in cur.fetchall()]
                    if not dry_run and ids:
                        conn.executemany("DELETE FROM entries WHERE id = ?", [(i,) for i in ids])
                    removed += len(ids)
                if not dry_run:
                    conn.commit()
            finally:
                conn.close()
        self._record_health()
        return {"ok": True, "removed": removed, "dry_run": dry_run}

    def health(self) -> Dict[str, Any]:
        metrics: Dict[str, Any] = {"db_path": str(_DB_PATH), "types": {}}
        total = 0
        with _lock:
            conn = sqlite3.connect(str(_DB_PATH))
            try:
                for mt in MEMORY_TYPES:
                    n = conn.execute(
                        "SELECT COUNT(*) FROM entries WHERE memory_type = ?", (mt,)
                    ).fetchone()[0]
                    metrics["types"][mt] = n
                    total += n
                metrics["total_entries"] = total
                metrics["db_size_bytes"] = _DB_PATH.stat().st_size if _DB_PATH.is_file() else 0
                row = conn.execute(
                    "SELECT metrics FROM health_snapshots ORDER BY id DESC LIMIT 1"
                ).fetchone()
                if row:
                    metrics["last_snapshot"] = json.loads(row[0])
            finally:
                conn.close()
        metrics["status"] = "healthy" if total >= 0 else "degraded"
        metrics["recorded_at"] = _utc()
        return metrics

    def _record_health(self) -> None:
        h = self.health()
        with _lock:
            conn = sqlite3.connect(str(_DB_PATH))
            try:
                conn.execute(
                    "INSERT INTO health_snapshots (recorded_at, metrics) VALUES (?, ?)",
                    (_utc(), json.dumps(h)),
                )
                conn.commit()
            finally:
                conn.close()

    def _fetch(self, sql: str, params: tuple) -> List[Dict[str, Any]]:
        with _lock:
            conn = sqlite3.connect(str(_DB_PATH))
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(sql, params).fetchall()
                out = []
                for r in rows:
                    d = dict(r)
                    try:
                        d["metadata"] = json.loads(d.get("metadata") or "{}")
                    except Exception:
                        d["metadata"] = {}
                    out.append(d)
                return out
            finally:
                conn.close()


_engine: Optional[Memory2Engine] = None


def get_memory2_engine() -> Memory2Engine:
    global _engine
    if _engine is None:
        _engine = Memory2Engine()
    return _engine
