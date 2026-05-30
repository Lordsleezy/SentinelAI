from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional

import db


MODEL_SPECS = [
    {
        "model_name": "sentinel-brain",
        "ollama_tag": "qwen3:8b",
        "role": "Orchestrator brain, routing, conversation",
        "size_gb": 5.2,
        "min_vram_gb": 6.0,
        "task_types": ["chat", "route", "plan", "general"],
    },
    {
        "model_name": "sentinel-coder",
        "ollama_tag": "qwen2.5-coder:14b",
        "role": "Code writing, Forge tasks, debugging",
        "size_gb": 9.0,
        "min_vram_gb": 9.0,
        "task_types": ["code", "forge", "repair", "build"],
    },
    {
        "model_name": "sentinel-reason",
        "ollama_tag": "deepseek-r1:8b",
        "role": "Hard reasoning, complex debugging, planning",
        "size_gb": 5.2,
        "min_vram_gb": 6.0,
        "task_types": ["reason", "debug", "analyze", "math"],
    },
    {
        "model_name": "sentinel-vision",
        "ollama_tag": "llava:7b",
        "role": "Vision, images, screenshots, blueprints",
        "size_gb": 4.7,
        "min_vram_gb": 6.0,
        "task_types": ["vision", "image", "screenshot", "blueprint"],
    },
    {
        "model_name": "sentinel-memory",
        "ollama_tag": "nomic-embed-text",
        "role": "Embeddings, semantic search, memory",
        "size_gb": 0.3,
        "min_vram_gb": 1.0,
        "task_types": ["embed", "search", "memory", "recall"],
    },
]

TIER_VRAM = {
    "minimal": 1.0,
    "basic": 8.0,
    "standard": 12.0,
    "full": 16.0,
    "unlimited": float("inf"),
}


def init_registry() -> None:
    _ensure_table()
    with db.get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) AS cnt FROM model_registry").fetchone()["cnt"]
        if count:
            return
        for spec in MODEL_SPECS:
            conn.execute(
                """INSERT INTO model_registry
                   (model_name, ollama_tag, role, size_gb, min_vram_gb, task_types)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    spec["model_name"],
                    spec["ollama_tag"],
                    spec["role"],
                    spec["size_gb"],
                    spec["min_vram_gb"],
                    json.dumps(spec["task_types"]),
                ),
            )


def get_model_for_task(task_type) -> Optional[Dict]:
    init_registry()
    task = str(task_type).lower()
    for model in get_all_models():
        if task in [item.lower() for item in model["task_types"]]:
            return model
    return None


def get_models_for_tier(tier) -> List[Dict]:
    init_registry()
    limit = TIER_VRAM.get(str(tier), 0.0)
    return [model for model in get_all_models() if float(model["min_vram_gb"]) <= limit]


def mark_downloaded(ollama_tag, downloaded=True) -> None:
    init_registry()
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE model_registry SET downloaded = ?, download_progress = ? WHERE ollama_tag = ?",
            (1 if downloaded else 0, 100.0 if downloaded else 0.0, ollama_tag),
        )


def update_progress(ollama_tag, progress_float) -> None:
    init_registry()
    progress = max(0.0, min(100.0, float(progress_float)))
    with db.get_conn() as conn:
        conn.execute(
            "UPDATE model_registry SET download_progress = ? WHERE ollama_tag = ?",
            (progress, ollama_tag),
        )


def record_use(ollama_tag) -> None:
    init_registry()
    with db.get_conn() as conn:
        conn.execute(
            """UPDATE model_registry
               SET last_used = ?, use_count = COALESCE(use_count, 0) + 1
               WHERE ollama_tag = ?""",
            (datetime.now().isoformat(), ollama_tag),
        )


def get_all_models() -> List[Dict]:
    init_registry()
    with db.get_conn() as conn:
        rows = conn.execute("SELECT * FROM model_registry ORDER BY id").fetchall()
        return [_row_to_dict(row) for row in rows]


def get_downloaded_models() -> List[Dict]:
    init_registry()
    with db.get_conn() as conn:
        rows = conn.execute("SELECT * FROM model_registry WHERE downloaded = 1 ORDER BY id").fetchall()
        return [_row_to_dict(row) for row in rows]


def _ensure_table() -> None:
    db.init_db()
    with db.get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS model_registry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model_name TEXT UNIQUE NOT NULL,
                ollama_tag TEXT NOT NULL,
                role TEXT NOT NULL,
                size_gb FLOAT NOT NULL,
                min_vram_gb FLOAT NOT NULL,
                task_types TEXT NOT NULL,
                downloaded INTEGER DEFAULT 0,
                download_progress FLOAT DEFAULT 0.0,
                last_used TEXT,
                use_count INTEGER DEFAULT 0
            )
            """
        )


def _row_to_dict(row) -> Dict:
    item = dict(row)
    try:
        item["task_types"] = json.loads(item.get("task_types") or "[]")
    except Exception:
        item["task_types"] = []
    item["downloaded"] = bool(item.get("downloaded"))
    item["size_gb"] = float(item.get("size_gb") or 0)
    item["min_vram_gb"] = float(item.get("min_vram_gb") or 0)
    item["download_progress"] = float(item.get("download_progress") or 0)
    return item
