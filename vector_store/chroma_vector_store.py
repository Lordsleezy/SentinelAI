"""Optional ChromaDB vector-store adapter."""

from typing import Any, Dict, List, Optional

from embeddings import LocalEmbeddingProvider


try:
    import chromadb  # type: ignore
except Exception:  # pragma: no cover
    chromadb = None


class ChromaVectorStore:
    """Chroma-backed store with the same minimal interface as SQLiteVectorStore."""

    def __init__(self, collection_name: str = "sentinelai_memory"):
        self.collection_name = collection_name
        self.embedding_provider = LocalEmbeddingProvider()
        self.client = chromadb.PersistentClient(path="data/chroma") if chromadb else None
        self.collection = self.client.get_or_create_collection(collection_name) if self.client else None

    def available(self) -> bool:
        return self.collection is not None

    def initialize(self) -> None:
        if not self.available():
            raise RuntimeError("chromadb is not installed")

    def add(self, namespace: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        self.initialize()
        item_id = f"{namespace}-{abs(hash(content))}"
        meta = metadata or {}
        meta["namespace"] = namespace
        self.collection.add(
            ids=[item_id],
            documents=[content],
            embeddings=[self.embedding_provider.embed(content)],
            metadatas=[meta],
        )
        return item_id

    def search(self, namespace: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        self.initialize()
        result = self.collection.query(
            query_embeddings=[self.embedding_provider.embed(query)],
            n_results=limit,
            where={"namespace": namespace},
        )
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        return [
            {
                "namespace": namespace,
                "content": doc,
                "metadata": meta or {},
                "score": 1.0 - float(distance or 0),
            }
            for doc, meta, distance in zip(documents, metadatas, distances)
        ]
