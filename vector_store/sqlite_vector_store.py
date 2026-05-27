"""
SQLite vector store for SentinelAI.

This store is the default persistence backend. Optional Qdrant/Chroma adapters
can be layered later without changing callers.
"""

import json
from typing import Any, Dict, List, Optional

import db
from embeddings import LocalEmbeddingProvider


class SQLiteVectorStore:
    """Persistent vector memory using SQLite + deterministic embeddings."""

    def __init__(self, embedding_provider: Optional[LocalEmbeddingProvider] = None):
        self.embedding_provider = embedding_provider or LocalEmbeddingProvider()

    def initialize(self) -> None:
        with db.get_conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS vector_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    namespace TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT DEFAULT '{}',
                    embedding_json TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_vector_memory_namespace
                ON vector_memory(namespace, updated_at);
                """
            )

    def add(self, namespace: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> int:
        self.initialize()
        embedding = self.embedding_provider.embed(content)
        with db.get_conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO vector_memory (namespace, content, metadata_json, embedding_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    namespace,
                    content,
                    json.dumps(metadata or {}, sort_keys=True),
                    json.dumps(embedding),
                ),
            )
            return cur.lastrowid

    def search(self, namespace: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        self.initialize()
        query_embedding = self.embedding_provider.embed(query)
        with db.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM vector_memory
                WHERE namespace = ?
                ORDER BY updated_at DESC
                LIMIT 500
                """,
                (namespace,),
            ).fetchall()

        scored = []
        for row in rows:
            try:
                embedding = json.loads(row["embedding_json"])
                metadata = json.loads(row["metadata_json"] or "{}")
            except Exception:
                embedding = []
                metadata = {}
            score = self.embedding_provider.cosine(query_embedding, embedding)
            scored.append(
                {
                    "id": row["id"],
                    "namespace": row["namespace"],
                    "content": row["content"],
                    "metadata": metadata,
                    "score": score,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return sorted(scored, key=lambda item: item["score"], reverse=True)[:limit]
