"""
memory_manager.py — Persistent Memory System for SentinelAI
Manages the Obsidian vault at ~/memory/vault/
"""
import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional


class MemoryManager:
    """Manages persistent memory storage in Obsidian vault format (.md files)"""

    def __init__(self, vault_root: Optional[Path] = None):
        if vault_root is None:
            vault_root = Path(__file__).parent / "memory" / "vault"

        self.vault_root = Path(vault_root)
        self.sessions_dir = self.vault_root / "sessions"
        self.contacts_dir = self.vault_root / "contacts"
        self.forge_logs_dir = self.vault_root / "forge_logs"
        self.earn_jobs_dir = self.vault_root / "earn_jobs"
        self.market_dir = self.vault_root / "market"
        self.calendar_dir = self.vault_root / "calendar"
        self.notes_dir = self.vault_root / "notes"

        # Ensure all subdirectories exist
        for subdir in [self.sessions_dir, self.contacts_dir, self.forge_logs_dir,
                      self.earn_jobs_dir, self.market_dir, self.calendar_dir, self.notes_dir]:
            subdir.mkdir(parents=True, exist_ok=True)

    def write_session(self, session_id: str, summary_dict: Dict[str, Any]) -> Path:
        """Write a session summary to sessions/"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"session_{session_id}_{timestamp}.md"
        filepath = self.sessions_dir / filename

        content = f"""# Session {session_id}

**Date:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## Summary
{summary_dict.get('summary', 'No summary provided')}

## Tasks Completed
{self._format_list(summary_dict.get('tasks_completed', []))}

## Workers Activated
{self._format_list(summary_dict.get('workers_activated', []))}

## Approvals
- Approved: {summary_dict.get('approvals_approved', 0)}
- Denied: {summary_dict.get('approvals_denied', 0)}

## Metrics
- Total execution time: {summary_dict.get('total_execution_time', 'N/A')}
- Backend uptime: {summary_dict.get('backend_uptime', 'N/A')}

## Notes
{summary_dict.get('notes', 'None')}
"""

        filepath.write_text(content, encoding='utf-8')
        return filepath

    def write_forge_log(self, task_id: str, result_dict: Dict[str, Any]) -> Path:
        """Write a Forge task result to forge_logs/"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"forge_{task_id}_{timestamp}.md"
        filepath = self.forge_logs_dir / filename

        content = f"""# Forge Task: {task_id}

**Date:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Status:** {result_dict.get('status', 'unknown')}

## Task Description
{result_dict.get('description', 'No description')}

## Prompt
```
{result_dict.get('prompt', 'No prompt provided')}
```

## Result
{result_dict.get('result', 'No result')}

## Files Modified
{self._format_list(result_dict.get('files_modified', []))}

## Execution Time
{result_dict.get('execution_time', 'N/A')}

## Errors
{result_dict.get('errors', 'None')}
"""

        filepath.write_text(content, encoding='utf-8')
        return filepath

    def write_earn_job(self, job_dict: Dict[str, Any]) -> Path:
        """Write an Earn job to earn_jobs/"""
        job_id = job_dict.get('job_id', datetime.now().strftime("%Y%m%d_%H%M%S"))
        filename = f"job_{job_id}.md"
        filepath = self.earn_jobs_dir / filename

        content = f"""# Earn Job: {job_dict.get('title', 'Untitled')}

**Source:** {job_dict.get('source', 'unknown')}
**Fetched:** {job_dict.get('fetched_at', datetime.now().isoformat())}
**Job ID:** {job_id}

## Details
- **Program:** {job_dict.get('program', 'N/A')}
- **Scope:** {job_dict.get('scope', 'N/A')}
- **Reward Range:** {job_dict.get('reward_range', 'N/A')}
- **URL:** {job_dict.get('url', 'N/A')}

## Description
{job_dict.get('description', 'No description provided')}

## Status
{job_dict.get('status', 'new')}

## Notes
{job_dict.get('notes', '')}
"""

        filepath.write_text(content, encoding='utf-8')
        return filepath

    def read_recent(self, subdir: str, n: int = 10) -> List[Dict[str, Any]]:
        """Read the most recent n .md files from a subdirectory"""
        subdir_map = {
            'sessions': self.sessions_dir,
            'contacts': self.contacts_dir,
            'forge_logs': self.forge_logs_dir,
            'earn_jobs': self.earn_jobs_dir,
            'market': self.market_dir,
            'calendar': self.calendar_dir,
            'notes': self.notes_dir
        }

        target_dir = subdir_map.get(subdir)
        if not target_dir or not target_dir.exists():
            return []

        # Get all .md files, sorted by modification time (newest first)
        md_files = sorted(
            [f for f in target_dir.glob("*.md")],
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )[:n]

        results = []
        for filepath in md_files:
            try:
                content = filepath.read_text(encoding='utf-8')
                results.append({
                    'filename': filepath.name,
                    'path': str(filepath),
                    'content': content,
                    'modified_at': datetime.fromtimestamp(filepath.stat().st_mtime).isoformat()
                })
            except Exception as e:
                print(f"Error reading {filepath}: {e}")
                continue

        return results

    def search_vault(self, query: str, max_results: int = 20) -> List[Dict[str, Any]]:
        """Simple grep-based search across all .md files in the vault"""
        query_lower = query.lower()
        results = []

        for md_file in self.vault_root.rglob("*.md"):
            try:
                content = md_file.read_text(encoding='utf-8')
                if query_lower in content.lower():
                    # Extract context around the match
                    lines = content.split('\n')
                    matched_lines = [line for line in lines if query_lower in line.lower()]

                    results.append({
                        'filename': md_file.name,
                        'path': str(md_file),
                        'relative_path': str(md_file.relative_to(self.vault_root)),
                        'matches': matched_lines[:3],  # First 3 matching lines
                        'modified_at': datetime.fromtimestamp(md_file.stat().st_mtime).isoformat()
                    })

                    if len(results) >= max_results:
                        break

            except Exception as e:
                print(f"Error searching {md_file}: {e}")
                continue

        return results

    def _format_list(self, items: List[str]) -> str:
        """Format a list as markdown bullets"""
        if not items:
            return "- None"
        return "\n".join(f"- {item}" for item in items)


# Singleton instance
_memory_manager = None


def get_memory_manager() -> MemoryManager:
    """Get or create the global MemoryManager instance"""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
