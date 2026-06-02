"""
workers/memory/memory_manager_v2.py
3-layer memory system for SentinelAI.

Layer 1 — Hot (SQLite): last 7 days, exact text, fast lookup
Layer 2 — Warm (ChromaDB vectors): 7+ days old, semantic embeddings
Layer 3 — Cold (markdown vault): extracted facts and decisions

A 10,000 word conversation becomes ~3KB after processing.
"""
from __future__ import annotations

import json
import logging
import os

# Suppress ChromaDB telemetry noise before lazy import
logging.getLogger('chromadb.telemetry').setLevel(logging.CRITICAL)
logging.getLogger('chromadb').setLevel(logging.WARNING)
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).parent.parent.parent
_DB_PATH = _BASE_DIR / "memory" / "hot_memory.db"
_CHROMA_PATH = _BASE_DIR / "memory" / "chroma_db"
_VAULT_PATH = _BASE_DIR / "memory" / "vault"

HOT_RETENTION_DAYS = 7


@dataclass
class MemoryEntry:
    id: str
    content: str
    source: str          # "user" | "claude" | "chatgpt" | "sentinel"
    topic: str = ""
    project: str = ""
    importance: int = 5
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    layer: str = "hot"   # "hot" | "warm" | "cold"
    relevance_score: float = 0.0

    def to_dict(self):
        return {k: getattr(self, k) for k in
                ("id", "content", "source", "topic", "project",
                 "importance", "created_at", "layer", "relevance_score")}


class MemoryManagerV2:
    """
    3-layer memory: Hot → Warm → Cold promotion pipeline.
    All writes go to hot first.
    Background job promotes old entries to warm/cold.
    """

    def __init__(self, socketio=None):
        self.socketio = socketio
        self._lock = threading.Lock()
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _VAULT_PATH.mkdir(parents=True, exist_ok=True)
        self._init_hot_db()
        self._chroma = None   # lazy-initialized
        self._embedder = None  # lazy-initialized
        self._start_promotion_job()

    # ── Lazy init ──────────────────────────────────────────────────────────────

    def _get_chroma(self):
        if self._chroma is not None:
            return self._chroma
        try:
            import chromadb
            _CHROMA_PATH.mkdir(parents=True, exist_ok=True)
            self._chroma = chromadb.PersistentClient(
                path=str(_CHROMA_PATH),
                settings=chromadb.Settings(anonymized_telemetry=False)
            )
            self._warm_collection = self._chroma.get_or_create_collection(
                name="sentinel_warm",
                metadata={"hnsw:space": "cosine"}
            )
        except Exception as e:
            logger.warning("[MemV2] ChromaDB init failed: %s", e)
            self._chroma = None
        return self._chroma

    def _get_embedder(self):
        if self._embedder is not None:
            return self._embedder
        try:
            from sentence_transformers import SentenceTransformer
            self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
        except Exception as e:
            logger.warning("[MemV2] SentenceTransformer not available: %s", e)
        return self._embedder

    def _embed(self, text: str) -> Optional[List[float]]:
        embedder = self._get_embedder()
        if embedder is None:
            return None
        try:
            return embedder.encode(text[:512], normalize_embeddings=True).tolist()
        except Exception as e:
            logger.debug("[MemV2] Embed failed: %s", e)
            return None

    # ── Hot layer (SQLite) ─────────────────────────────────────────────────────

    def _init_hot_db(self):
        with sqlite3.connect(str(_DB_PATH)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS hot_memory (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    source TEXT DEFAULT 'user',
                    topic TEXT DEFAULT '',
                    project TEXT DEFAULT '',
                    importance INTEGER DEFAULT 5,
                    created_at TEXT NOT NULL,
                    promoted INTEGER DEFAULT 0
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_created ON hot_memory(created_at)")
            conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS hot_fts USING fts5(id UNINDEXED, content, source, topic)")
            conn.commit()

    def _hot_write(self, entry: MemoryEntry):
        try:
            with sqlite3.connect(str(_DB_PATH)) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO hot_memory VALUES (?,?,?,?,?,?,?,0)",
                    (entry.id, entry.content, entry.source,
                     entry.topic, entry.project, entry.importance, entry.created_at)
                )
                # Keep FTS in sync
                conn.execute("INSERT OR REPLACE INTO hot_fts VALUES (?,?,?,?)",
                             (entry.id, entry.content, entry.source, entry.topic))
                conn.commit()
        except Exception as e:
            logger.warning("[MemV2] Hot write failed: %s", e)

    def _hot_search(self, query: str, limit: int = 10) -> List[MemoryEntry]:
        results = []
        try:
            with sqlite3.connect(str(_DB_PATH)) as conn:
                # FTS search
                rows = conn.execute(
                    "SELECT id, content, source, topic FROM hot_fts WHERE hot_fts MATCH ? LIMIT ?",
                    (query, limit)
                ).fetchall()
                if not rows:
                    # Fallback: LIKE search
                    rows2 = conn.execute(
                        "SELECT id, content, source, topic FROM hot_memory WHERE content LIKE ? LIMIT ?",
                        (f"%{query}%", limit)
                    ).fetchall()
                    rows = rows2
                for row in rows:
                    results.append(MemoryEntry(
                        id=row[0], content=row[1], source=row[2], topic=row[3] or "",
                        layer="hot"
                    ))
        except Exception as e:
            logger.debug("[MemV2] Hot search failed: %s", e)
        return results

    def _hot_recent(self, limit: int = 20) -> List[MemoryEntry]:
        results = []
        try:
            with sqlite3.connect(str(_DB_PATH)) as conn:
                rows = conn.execute(
                    "SELECT id, content, source, topic, project, importance, created_at FROM hot_memory ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
                for r in rows:
                    results.append(MemoryEntry(
                        id=r[0], content=r[1], source=r[2], topic=r[3] or "",
                        project=r[4] or "", importance=r[5] or 5, created_at=r[6], layer="hot"
                    ))
        except Exception as e:
            logger.debug("[MemV2] Hot recent failed: %s", e)
        return results

    def _hot_count(self) -> int:
        try:
            with sqlite3.connect(str(_DB_PATH)) as conn:
                return conn.execute("SELECT COUNT(*) FROM hot_memory").fetchone()[0]
        except Exception:
            return 0

    def _hot_size_mb(self) -> float:
        try:
            return _DB_PATH.stat().st_size / (1024 * 1024)
        except Exception:
            return 0.0

    # ── Write API ──────────────────────────────────────────────────────────────

    def remember(self, content: str, source: str = "user", topic: str = "",
                 project: str = "", importance: int = 5) -> str:
        entry = MemoryEntry(
            id=str(uuid.uuid4()),
            content=content[:4000],
            source=source,
            topic=topic,
            project=project,
            importance=importance,
        )
        self._hot_write(entry)
        return entry.id

    def process_conversation(self, conv) -> None:
        """Process a full conversation object into the memory pipeline."""
        try:
            # Save to hot layer
            content = f"[{conv.platform}] {conv.title}\n"
            if hasattr(conv, 'messages'):
                for m in (conv.messages or [])[:20]:
                    role = m.get("role", "")
                    txt = m.get("content", "")[:300]
                    content += f"{role}: {txt}\n"

            self.remember(
                content=content,
                source=conv.platform,
                topic=conv.title[:100],
                importance=5,
            )
        except Exception as e:
            logger.debug("[MemV2] process_conversation failed: %s", e)

    def write_session(self, data: dict):
        """Compatibility wrapper."""
        content = data.get("content") or data.get("title") or str(data)
        self.remember(content, source=data.get("source", "system"),
                      topic=data.get("title", ""), project=data.get("project", ""))

    def purge_by_source(self, source: str) -> int:
        """Delete all memories with the given source from all layers."""
        count = 0
        # Hot layer
        try:
            with sqlite3.connect(str(_DB_PATH)) as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM hot_memory WHERE source = ?", (source,))
                count += cur.rowcount
                # Keep FTS in sync
                cur.execute("DELETE FROM hot_fts WHERE source = ?", (source,))
                conn.commit()
        except Exception as e:
            logger.warning("[MemV2] purge_by_source hot failed: %s", e)

        # Cold vault — delete markdown files with matching source frontmatter
        import glob as _glob
        vault_pattern = str(_VAULT_PATH / "**" / "*.md")
        try:
            for f in _glob.glob(vault_pattern, recursive=True):
                try:
                    with open(f, 'r', encoding='utf-8', errors='ignore') as fp:
                        content = fp.read()
                    if f'source: {source}' in content:
                        os.remove(f)
                        count += 1
                except Exception:
                    pass
        except Exception as e:
            logger.warning("[MemV2] purge_by_source cold failed: %s", e)

        # Warm layer (ChromaDB) — delete by source metadata
        try:
            chroma = self._get_chroma()
            if chroma:
                self._warm_collection.delete(where={"source": source})
        except Exception as e:
            logger.debug("[MemV2] purge_by_source warm failed: %s", e)

        logger.info("[MemV2] Purged %d entries for source: %s", count, source)
        return count

    def purge_all(self) -> int:
        """Wipe all memories from all layers."""
        count = 0
        try:
            with sqlite3.connect(str(_DB_PATH)) as conn:
                cur = conn.cursor()
                cur.execute("DELETE FROM hot_memory")
                count = cur.rowcount
                cur.execute("DELETE FROM hot_fts")
                conn.commit()
        except Exception as e:
            logger.warning("[MemV2] purge_all failed: %s", e)
        return count

    def write_forge_log(self, data: dict):
        content = f"Forge: {data.get('task', '')} -> {data.get('result', '')}"
        self.remember(content, source="forge", topic="forge", importance=4)

    def write_earn_job(self, data: dict):
        content = f"Earn: {data.get('program', '')} status={data.get('status', '')}"
        self.remember(content, source="earn", topic="earn", importance=3)

    # ── Read API ───────────────────────────────────────────────────────────────

    def recall(self, query: str, limit: int = 5,
               sources: Optional[List[str]] = None) -> List[MemoryEntry]:
        results = []

        # Hot: FTS search
        hot = self._hot_search(query, limit * 2)
        results.extend(hot)

        # Warm: ChromaDB semantic search
        warm = self._warm_search(query, limit)
        results.extend(warm)

        # Cold: vault keyword search
        cold = self._cold_search(query, limit)
        results.extend(cold)

        # Filter by source if requested
        if sources:
            results = [r for r in results if r.source in sources]

        # Deduplicate by content prefix and return top results
        seen = set()
        unique = []
        for r in results:
            key = r.content[:80]
            if key not in seen:
                seen.add(key)
                unique.append(r)

        return unique[:limit]

    def _warm_search(self, query: str, limit: int = 5) -> List[MemoryEntry]:
        results = []
        try:
            chroma = self._get_chroma()
            if chroma is None:
                return results
            embedding = self._embed(query)
            if embedding is None:
                return results
            res = self._warm_collection.query(
                query_embeddings=[embedding],
                n_results=min(limit, self._warm_collection.count())
            )
            for i, doc in enumerate(res.get("documents", [[]])[0]):
                meta = (res.get("metadatas", [[]])[0] or [{}])[i] or {}
                results.append(MemoryEntry(
                    id=meta.get("id", str(uuid.uuid4())),
                    content=doc,
                    source=meta.get("source", ""),
                    topic=meta.get("topic", ""),
                    layer="warm",
                    relevance_score=1 - ((res.get("distances", [[]])[0] or [1])[i] or 1),
                ))
        except Exception as e:
            logger.debug("[MemV2] Warm search failed: %s", e)
        return results

    def _cold_search(self, query: str, limit: int = 5) -> List[MemoryEntry]:
        results = []
        words = [w.lower() for w in re.split(r'\W+', query) if len(w) > 3]
        if not words:
            return results
        try:
            for f in list(_VAULT_PATH.rglob("*.md"))[:50]:
                try:
                    text = f.read_text(encoding="utf-8")
                    if any(w in text.lower() for w in words):
                        results.append(MemoryEntry(
                            id=f.stem,
                            content=text[:1000],
                            source="cold",
                            topic=f.stem,
                            layer="cold",
                        ))
                        if len(results) >= limit:
                            break
                except Exception:
                    pass
        except Exception as e:
            logger.debug("[MemV2] Cold search failed: %s", e)
        return results

    def recall_about_topic(self, topic: str) -> List[MemoryEntry]:
        return self.recall(topic, limit=10)

    def recall_from_source(self, source: str, topic: str = "") -> List[MemoryEntry]:
        query = topic if topic else "recent"
        return self.recall(query, limit=10, sources=[source])

    def recall_from_claude(self, topic: str = "") -> List[MemoryEntry]:
        return self.recall_from_source("claude", topic)

    def recall_from_chatgpt(self, topic: str = "") -> List[MemoryEntry]:
        return self.recall_from_source("chatgpt", topic)

    def get_context_for_prompt(self, prompt: str, max_tokens: int = 2000) -> str:
        """Get relevant memory context string to prepend to any prompt."""
        memories = self.recall(prompt, limit=5)
        if not memories:
            # Fall back to recent memories
            memories = self._hot_recent(5)
        if not memories:
            return ""

        lines = []
        total = 0
        for m in memories:
            entry = f"[{m.source}] {m.topic or 'note'}: {m.content[:300]}"
            total += len(entry)
            if total > max_tokens * 4:
                break
            lines.append(entry)

        return "\n".join(lines)

    # ── Promotion pipeline ─────────────────────────────────────────────────────

    def _start_promotion_job(self):
        def _loop():
            while True:
                time.sleep(3600)
                try:
                    self._promote_hot_to_warm()
                except Exception as e:
                    logger.debug("[MemV2] Promotion error: %s", e)
        threading.Thread(target=_loop, daemon=True).start()

    def _promote_hot_to_warm(self):
        """Move entries older than HOT_RETENTION_DAYS to warm layer."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=HOT_RETENTION_DAYS)).isoformat()
        try:
            with sqlite3.connect(str(_DB_PATH)) as conn:
                rows = conn.execute(
                    "SELECT id, content, source, topic, project, importance, created_at FROM hot_memory WHERE created_at < ? AND promoted = 0 LIMIT 50",
                    (cutoff,)
                ).fetchall()

                for r in rows:
                    entry = MemoryEntry(
                        id=r[0], content=r[1], source=r[2], topic=r[3] or "",
                        project=r[4] or "", importance=r[5] or 5, created_at=r[6], layer="hot"
                    )
                    self._warm_write(entry)
                    self._extract_cold_facts(entry)
                    conn.execute("UPDATE hot_memory SET promoted=1 WHERE id=?", (entry.id,))

                conn.commit()
                if rows:
                    logger.info("[MemV2] Promoted %d entries to warm/cold", len(rows))
        except Exception as e:
            logger.warning("[MemV2] Promotion failed: %s", e)

    def _warm_write(self, entry: MemoryEntry):
        """Write entry to ChromaDB warm layer."""
        try:
            chroma = self._get_chroma()
            if chroma is None:
                return
            embedding = self._embed(entry.content)
            if embedding is None:
                return
            self._warm_collection.upsert(
                ids=[entry.id],
                documents=[entry.content[:512]],
                embeddings=[embedding],
                metadatas=[{
                    "id": entry.id,
                    "source": entry.source,
                    "topic": entry.topic,
                    "project": entry.project,
                    "importance": str(entry.importance),
                    "created_at": entry.created_at,
                }]
            )
        except Exception as e:
            logger.debug("[MemV2] Warm write failed: %s", e)

    def _extract_cold_facts(self, entry: MemoryEntry):
        """Save key facts as structured markdown to the vault."""
        try:
            vault_dir = _VAULT_PATH / "facts"
            vault_dir.mkdir(parents=True, exist_ok=True)
            safe_topic = "".join(c if c.isalnum() or c in " -_" else "_"
                                  for c in (entry.topic or entry.source or "note"))[:50]
            date_str = entry.created_at[:10]
            filename = f"{date_str}_{entry.source}_{safe_topic}.md"
            path = vault_dir / filename

            if path.exists():
                return

            content = f"""---
source: {entry.source}
date: {date_str}
topic: {entry.topic}
project: {entry.project or 'general'}
importance: {entry.importance}
---
{entry.content[:2000]}
"""
            path.write_text(content, encoding="utf-8")
        except Exception as e:
            logger.debug("[MemV2] Cold extract failed: %s", e)

    # ── Stats ──────────────────────────────────────────────────────────────────

    def get_recent(self, limit: int = 20, type_filter: str = None, since: str = None) -> list:
        """Query hot layer for recent entries with optional type and since filters."""
        results = []
        try:
            query = "SELECT id, content, source, topic, project, importance, created_at FROM hot_memory WHERE 1=1"
            params: list = []
            if type_filter:
                query += " AND source = ?"
                params.append(type_filter)
            if since:
                query += " AND created_at >= ?"
                params.append(since)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            with sqlite3.connect(str(_DB_PATH)) as conn:
                rows = conn.execute(query, params).fetchall()
                for r in rows:
                    results.append({
                        'id': r[0], 'content': r[1], 'source': r[2],
                        'topic': r[3] or '', 'project': r[4] or '',
                        'importance': r[5] or 5, 'created_at': r[6],
                    })
        except Exception as e:
            logger.debug("[MemV2] get_recent failed: %s", e)
        return results

    def get_chat_sessions(self) -> list:
        """Return past chat sessions grouped by day from hot memory."""
        sessions = []
        try:
            with sqlite3.connect(str(_DB_PATH)) as conn:
                rows = conn.execute(
                    """SELECT DATE(created_at) as day,
                              COUNT(*) as cnt,
                              MIN(content) as preview,
                              MIN(created_at) as first_ts,
                              MAX(created_at) as last_ts
                       FROM hot_memory
                       WHERE source IN ('user', 'sentinel', 'claude', 'chatgpt')
                       GROUP BY day
                       ORDER BY day DESC
                       LIMIT 30"""
                ).fetchall()
                for r in rows:
                    day, cnt, preview, first_ts, last_ts = r
                    sessions.append({
                        'date': day,
                        'count': cnt,
                        'preview': (preview or '')[:100],
                        'first_ts': first_ts,
                        'last_ts': last_ts,
                    })
        except Exception as e:
            logger.debug("[MemV2] get_chat_sessions failed: %s", e)
        return sessions

    def get_stats(self) -> dict:
        hot_count = self._hot_count()
        hot_size = self._hot_size_mb()

        warm_count = 0
        warm_size = 0.0
        try:
            chroma = self._get_chroma()
            if chroma:
                warm_count = self._warm_collection.count()
                warm_size = sum(f.stat().st_size for f in _CHROMA_PATH.rglob("*") if f.is_file()) / (1024 * 1024)
        except Exception:
            pass

        cold_files = len(list(_VAULT_PATH.rglob("*.md")))
        cold_size = sum(f.stat().st_size for f in _VAULT_PATH.rglob("*.md")) / (1024 * 1024)

        return {
            "hot_entries": hot_count,
            "hot_size_mb": round(hot_size, 2),
            "warm_entries": warm_count,
            "warm_size_mb": round(warm_size, 2),
            "cold_files": cold_files,
            "cold_size_mb": round(cold_size, 2),
            "total_size_mb": round(hot_size + warm_size + cold_size, 2),
            "oldest_memory": self._oldest_memory(),
            "conversations_stored": cold_files,
        }

    def _oldest_memory(self) -> str:
        try:
            with sqlite3.connect(str(_DB_PATH)) as conn:
                row = conn.execute("SELECT MIN(created_at) FROM hot_memory").fetchone()
                return row[0] or "none"
        except Exception:
            return "unknown"


# Singleton
_v2_instance: Optional[MemoryManagerV2] = None
_v2_lock = threading.Lock()


def get_memory_manager_v2(socketio=None) -> MemoryManagerV2:
    global _v2_instance
    with _v2_lock:
        if _v2_instance is None:
            _v2_instance = MemoryManagerV2(socketio=socketio)
    return _v2_instance
