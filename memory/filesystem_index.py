"""Persistent filesystem and workspace awareness."""

import hashlib
import os
from pathlib import Path
from typing import Dict, List, Optional

import db
from memory.persistent_memory import get_memory


DEFAULT_IGNORE_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    "venv",
    "env",
    ".venv",
    "data",
}


class FilesystemIndexer:
    """Indexes repository structure and selected file metadata."""

    def initialize(self) -> None:
        with db.get_conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS filesystem_index (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_root TEXT NOT NULL,
                    path TEXT NOT NULL,
                    rel_path TEXT NOT NULL,
                    file_type TEXT DEFAULT '',
                    size_bytes INTEGER DEFAULT 0,
                    content_hash TEXT DEFAULT '',
                    relationship_json TEXT DEFAULT '{}',
                    indexed_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(workspace_root, rel_path)
                );

                CREATE INDEX IF NOT EXISTS idx_filesystem_workspace
                ON filesystem_index(workspace_root, rel_path);
                """
            )

    def index_workspace(self, root: str, max_files: int = 1000) -> Dict:
        self.initialize()
        root_path = Path(root).resolve()
        if not root_path.exists():
            raise FileNotFoundError(str(root_path))

        files_indexed = 0
        dirs_seen = set()
        memory = get_memory()
        with db.get_conn() as conn:
            for path in root_path.rglob("*"):
                if files_indexed >= max_files:
                    break
                if any(part in DEFAULT_IGNORE_DIRS for part in path.parts):
                    continue
                if path.is_dir():
                    dirs_seen.add(str(path.relative_to(root_path)))
                    continue
                if not path.is_file():
                    continue

                rel_path = str(path.relative_to(root_path))
                size = path.stat().st_size
                digest = self._hash_file(path, size)
                file_type = path.suffix.lower().lstrip(".")
                conn.execute(
                    """
                    INSERT INTO filesystem_index
                    (workspace_root, path, rel_path, file_type, size_bytes, content_hash)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(workspace_root, rel_path)
                    DO UPDATE SET path = excluded.path, file_type = excluded.file_type,
                                  size_bytes = excluded.size_bytes,
                                  content_hash = excluded.content_hash,
                                  indexed_at = datetime('now')
                    """,
                    (str(root_path), str(path), rel_path, file_type, size, digest),
                )
                if size <= 25000 and file_type in {"py", "js", "ts", "md", "txt", "json", "html", "css"}:
                    try:
                        content = path.read_text(encoding="utf-8", errors="ignore")
                        memory.remember(
                            "codebase",
                            f"{rel_path}\n{content[:8000]}",
                            {"workspace_root": str(root_path), "path": str(path), "rel_path": rel_path},
                        )
                    except Exception:
                        pass
                files_indexed += 1

        db.log_event("filesystem_indexed", f"{root_path} files={files_indexed}")
        return {
            "workspace_root": str(root_path),
            "files_indexed": files_indexed,
            "directories_seen": len(dirs_seen),
        }

    def list_workspace_files(self, root: str, limit: int = 200) -> List[Dict]:
        self.initialize()
        root_path = str(Path(root).resolve())
        with db.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM filesystem_index
                WHERE workspace_root = ?
                ORDER BY rel_path ASC
                LIMIT ?
                """,
                (root_path, limit),
            ).fetchall()
            return [dict(row) for row in rows]

    def _hash_file(self, path: Path, size: int) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            digest.update(handle.read(65536 if size > 65536 else size))
        return digest.hexdigest()


_indexer: Optional[FilesystemIndexer] = None


def get_filesystem_indexer() -> FilesystemIndexer:
    global _indexer
    if _indexer is None:
        _indexer = FilesystemIndexer()
    return _indexer
