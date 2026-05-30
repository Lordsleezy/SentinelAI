from datetime import datetime
from typing import Dict, List, Optional

import db


def _now() -> str:
    return datetime.now().isoformat()


def register_tool(tool_name, description, entry_point, tool_type="built"):
    with db.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO capability_registry
                (tool_name, description, entry_point, tool_type, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(tool_name) DO UPDATE SET
                description = excluded.description,
                entry_point = excluded.entry_point,
                tool_type = excluded.tool_type
            """,
            (tool_name, description, entry_point, tool_type, _now()),
        )


def get_tool(tool_name) -> Optional[Dict]:
    with db.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM capability_registry WHERE tool_name = ?",
            (tool_name,),
        ).fetchone()
        return dict(row) if row else None


def list_tools() -> List[Dict]:
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM capability_registry ORDER BY tool_name ASC"
        ).fetchall()
        return [dict(row) for row in rows]


def record_tool_use(tool_name):
    with db.get_conn() as conn:
        conn.execute(
            """
            UPDATE capability_registry
               SET last_used = ?, use_count = COALESCE(use_count, 0) + 1
             WHERE tool_name = ?
            """,
            (_now(), tool_name),
        )


def tool_exists(tool_name) -> bool:
    return get_tool(tool_name) is not None


def find_tool_for_task(task_description) -> Optional[Dict]:
    task_words = {
        word.strip(".,:;!?()[]{}\"'").lower()
        for word in str(task_description).split()
        if len(word.strip(".,:;!?()[]{}\"'")) >= 3
    }
    if not task_words:
        return None

    best_tool = None
    best_score = 0
    for tool in list_tools():
        description = f"{tool.get('tool_name', '')} {tool.get('description', '')}".lower()
        score = sum(1 for word in task_words if word in description)
        if score > best_score:
            best_tool = tool
            best_score = score

    return best_tool if best_score > 0 else None


def register_builtin_tools():
    register_tool(
        "forge",
        "Autonomous coding and build agent. Builds software, scripts, and tools from a prompt.",
        "workers.forge_worker.run_forge_task",
        "worker",
    )
    register_tool(
        "repair",
        "Autonomous repair: fix bug in repository. Clones repos, generates patches, runs tests.",
        "executor.run_executor",
        "worker",
    )
    register_tool(
        "web_search",
        "Search and scrape the web. Fetch web pages and find GitHub issues.",
        "workers.web_worker.run_web_task",
        "worker",
    )
    register_tool(
        "guardian",
        "Security scanner. Scans files for threats and detects exposed API keys.",
        "workers.guardian_worker.run_guardian_task",
        "worker",
    )
    register_tool(
        "bounty_pipeline",
        "GitHub bounty revenue pipeline. Finds, scores, and queues repair opportunities.",
        "revenue.bounty_pipeline.run_pipeline_cycle",
        "worker",
    )
