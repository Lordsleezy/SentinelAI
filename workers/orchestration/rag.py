"""
RAG (Retrieval-Augmented Generation) — Vector search over codebase context
"""
import os
import logging
import threading
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

CAPABILITY_DESCRIPTION = "Retrieves relevant codebase context for tasks via semantic search"

try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False
    logger.warning("chromadb not available - RAG disabled")

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False
    logger.warning("sentence_transformers not available - RAG disabled")


class CodebaseRAG:
    """Vector retrieval over codebase using ChromaDB"""

    def __init__(self, codebase_root: str = None):
        self.codebase_root = codebase_root or os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        self.db_path = os.path.join(self.codebase_root, '.rag_db')
        self.indexed = False
        self.index_lock = threading.Lock()

        if CHROMADB_AVAILABLE and SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                self.client = chromadb.Client(Settings(
                    chroma_db_impl="duckdb+parquet",
                    persist_directory=self.db_path,
                    anonymized_telemetry=False
                ))
                self.model = SentenceTransformer('all-MiniLM-L6-v2')
                self.collection = None
            except Exception as e:
                logger.error(f"Failed to initialize ChromaDB: {e}")
                self.client = None
                self.model = None
        else:
            self.client = None
            self.model = None

    def index_codebase(self, force: bool = False) -> bool:
        """Index all Python files in the codebase"""
        if not CHROMADB_AVAILABLE or not SENTENCE_TRANSFORMERS_AVAILABLE:
            logger.warning("RAG dependencies not available - skipping indexing")
            return False

        if self.indexed and not force:
            return True

        if not self.client or not self.model:
            logger.error("RAG client not initialized")
            return False

        with self.index_lock:
            try:
                # Get or create collection
                try:
                    self.client.delete_collection(name="codebase")
                except:
                    pass

                self.collection = self.client.create_collection(
                    name="codebase",
                    metadata={"hnsw:space": "cosine"}
                )

                documents = []
                metadatas = []
                ids = []
                doc_id = 0

                # Walk through Python files
                for root, dirs, files in os.walk(self.codebase_root):
                    # Skip common directories
                    dirs[:] = [d for d in dirs if d not in [
                        '__pycache__', '.git', 'node_modules', '.rag_db',
                        'venv', 'env', '.env', 'dist', 'build'
                    ]]

                    for file in [f for f in files if f.endswith('.py')]:
                        try:
                            file_path = os.path.join(root, file)
                            relative_path = os.path.relpath(file_path, self.codebase_root)

                            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()

                            # Chunk by functions/classes
                            chunks = self._chunk_code(content, relative_path)

                            for chunk_text, chunk_meta in chunks:
                                if chunk_text.strip():
                                    documents.append(chunk_text)
                                    metadatas.append(chunk_meta)
                                    ids.append(f"doc_{doc_id}")
                                    doc_id += 1

                        except Exception as e:
                            logger.debug(f"Failed to index {file}: {e}")

                # Add to collection in batches
                batch_size = 100
                for i in range(0, len(documents), batch_size):
                    batch_docs = documents[i:i+batch_size]
                    batch_meta = metadatas[i:i+batch_size]
                    batch_ids = ids[i:i+batch_size]

                    if batch_docs:
                        embeddings = self.model.encode(batch_docs).tolist()
                        self.collection.add(
                            documents=batch_docs,
                            metadatas=batch_meta,
                            embeddings=embeddings,
                            ids=batch_ids
                        )

                self.indexed = True
                logger.info(f"Indexed {doc_id} code chunks from {self.codebase_root}")
                return True

            except Exception as e:
                logger.error(f"Indexing failed: {e}")
                return False

    def _chunk_code(self, content: str, file_path: str) -> List[tuple]:
        """Chunk Python code by functions and classes"""
        chunks = []
        lines = content.split('\n')

        current_chunk = []
        current_meta = None

        for i, line in enumerate(lines):
            # Detect function/class definitions
            if line.strip().startswith(('def ', 'class ')):
                # Save previous chunk if exists
                if current_chunk:
                    chunks.append(('\n'.join(current_chunk), current_meta))

                # Start new chunk
                current_chunk = [line]
                match_def = line.strip().split('(')[0].replace('def ', '').replace('class ', '')
                current_meta = {
                    "file": file_path,
                    "line": i + 1,
                    "type": "def" if "def " in line else "class",
                    "name": match_def
                }
            else:
                current_chunk.append(line)

            # Chunk every 50 lines or at end of file
            if len(current_chunk) >= 50 or i == len(lines) - 1:
                if current_chunk and current_chunk[0].strip():
                    chunks.append(('\n'.join(current_chunk), current_meta or {
                        "file": file_path,
                        "line": i + 1,
                        "type": "code",
                        "name": "chunk"
                    }))
                    current_chunk = []
                    current_meta = None

        return chunks

    def query(self, task: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """Query for relevant code context"""
        if not self.collection:
            logger.warning("RAG collection not initialized")
            return []

        if not self.indexed:
            logger.warning("Codebase not indexed - indexing now")
            self.index_codebase()

        try:
            query_embedding = self.model.encode([task])[0].tolist()

            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                include=["documents", "metadatas", "distances"]
            )

            formatted = []
            if results and results['documents']:
                for i, doc in enumerate(results['documents'][0]):
                    meta = results['metadatas'][0][i] if results['metadatas'] else {}
                    distance = results['distances'][0][i] if results['distances'] else 0

                    formatted.append({
                        "document": doc,
                        "file": meta.get('file', 'unknown'),
                        "line": meta.get('line', 0),
                        "type": meta.get('type', 'code'),
                        "name": meta.get('name', 'snippet'),
                        "relevance": max(0, 1 - distance)  # Convert distance to relevance
                    })

            return formatted

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []

    def get_context_for_task(self, task: str, max_chars: int = 3000) -> str:
        """Get formatted context string for a task"""
        results = self.query(task, n_results=5)

        if not results:
            return ""

        context_parts = []
        total_chars = 0

        for result in results:
            part = f"File: {result['file']} (line {result['line']})\n"
            part += f"{result['document']}\n"

            if total_chars + len(part) <= max_chars:
                context_parts.append(part)
                total_chars += len(part)
            else:
                break

        return '\n---\n'.join(context_parts)

    def reindex(self) -> bool:
        """Force reindex of codebase"""
        return self.index_codebase(force=True)

    def get_status(self) -> Dict[str, Any]:
        """Get RAG indexing status"""
        return {
            "indexed": self.indexed,
            "available": CHROMADB_AVAILABLE and SENTENCE_TRANSFORMERS_AVAILABLE,
            "db_path": self.db_path,
            "codebase_root": self.codebase_root
        }


# Global instance
_rag = None


def get_rag(codebase_root: str = None) -> CodebaseRAG:
    global _rag
    if _rag is None:
        _rag = CodebaseRAG(codebase_root)
    return _rag
