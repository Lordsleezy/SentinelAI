"""
learning.py — Learning and memory system for Sentinel Earn
Tracks PR outcomes, maintainer feedback, and success patterns
Enables the agent to learn from experience and improve over time
"""
import sqlite3
import logging
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


# ─── Database Schema ──────────────────────────────────────────────────────────

def init_learning_tables(db_path: Path):
    """
    Initialize learning memory tables.
    
    Args:
        db_path: Path to SQLite database
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    
    try:
        conn.executescript("""
            -- Repository memory: track repos we've interacted with
            CREATE TABLE IF NOT EXISTS repo_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_url TEXT UNIQUE NOT NULL,
                owner TEXT NOT NULL,
                repo_name TEXT NOT NULL,
                total_prs INTEGER DEFAULT 0,
                merged_prs INTEGER DEFAULT 0,
                rejected_prs INTEGER DEFAULT 0,
                last_interaction TEXT,
                maintainer_hostile INTEGER DEFAULT 0,  -- 1 if hostile to AI PRs
                notes TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            
            -- Fix patterns: track what works and what doesn't
            CREATE TABLE IF NOT EXISTS fix_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_type TEXT NOT NULL,  -- e.g., "NullPointerException", "typo", "import error"
                language TEXT NOT NULL,
                fix_approach TEXT NOT NULL,  -- JSON describing the fix
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                avg_confidence REAL DEFAULT 0.0,
                last_used TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            
            -- Maintainer feedback: track PR comments and reviews
            CREATE TABLE IF NOT EXISTS maintainer_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                opportunity_id INTEGER,
                pr_url TEXT NOT NULL,
                repo_url TEXT NOT NULL,
                feedback_type TEXT NOT NULL,  -- "comment", "review", "merge", "close"
                sentiment TEXT,  -- "positive", "neutral", "negative"
                feedback_text TEXT,
                extracted_lessons TEXT,  -- JSON array of lessons learned
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (opportunity_id) REFERENCES opportunities(id)
            );
            
            -- Success metrics: aggregate statistics
            CREATE TABLE IF NOT EXISTS success_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric_name TEXT UNIQUE NOT NULL,
                metric_value REAL NOT NULL,
                last_updated TEXT DEFAULT (datetime('now'))
            );
            
            -- Create indexes
            CREATE INDEX IF NOT EXISTS idx_repo_memory_url ON repo_memory(repo_url);
            CREATE INDEX IF NOT EXISTS idx_fix_patterns_type ON fix_patterns(issue_type, language);
            CREATE INDEX IF NOT EXISTS idx_feedback_repo ON maintainer_feedback(repo_url);
        """)
        
        conn.commit()
        logger.info("Learning tables initialized")
        
    except Exception as e:
        logger.error(f"Failed to initialize learning tables: {e}")
        conn.rollback()
    finally:
        conn.close()


# ─── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class RepoMemory:
    """Memory about a repository."""
    repo_url: str
    owner: str
    repo_name: str
    total_prs: int
    merged_prs: int
    rejected_prs: int
    merge_rate: float
    maintainer_hostile: bool
    notes: str


@dataclass
class FixPattern:
    """Pattern for successful fixes."""
    issue_type: str
    language: str
    fix_approach: Dict
    success_count: int
    failure_count: int
    success_rate: float
    avg_confidence: float


# ─── Repository Memory ────────────────────────────────────────────────────────

def record_pr_outcome(
    db_path: Path,
    repo_url: str,
    owner: str,
    repo_name: str,
    merged: bool,
    notes: Optional[str] = None
):
    """
    Record the outcome of a PR submission.
    
    Args:
        db_path: Path to SQLite database
        repo_url: Repository URL
        owner: Repository owner
        repo_name: Repository name
        merged: True if PR was merged, False if rejected
        notes: Optional notes about the outcome
    """
    conn = sqlite3.connect(str(db_path))
    
    try:
        # Check if repo exists
        existing = conn.execute(
            "SELECT id, total_prs, merged_prs, rejected_prs FROM repo_memory WHERE repo_url = ?",
            (repo_url,)
        ).fetchone()
        
        if existing:
            # Update existing record
            total = existing[1] + 1
            merged_count = existing[2] + (1 if merged else 0)
            rejected_count = existing[3] + (0 if merged else 1)
            
            conn.execute(
                """UPDATE repo_memory 
                   SET total_prs = ?, merged_prs = ?, rejected_prs = ?,
                       last_interaction = datetime('now'), notes = ?
                   WHERE repo_url = ?""",
                (total, merged_count, rejected_count, notes or "", repo_url)
            )
        else:
            # Insert new record
            conn.execute(
                """INSERT INTO repo_memory 
                   (repo_url, owner, repo_name, total_prs, merged_prs, rejected_prs, notes)
                   VALUES (?, ?, ?, 1, ?, ?, ?)""",
                (repo_url, owner, repo_name, 1 if merged else 0, 0 if merged else 1, notes or "")
            )
        
        conn.commit()
        logger.info(f"Recorded PR outcome for {repo_url}: merged={merged}")
        
    except Exception as e:
        logger.error(f"Failed to record PR outcome: {e}")
        conn.rollback()
    finally:
        conn.close()


def mark_maintainer_hostile(db_path: Path, repo_url: str, reason: str):
    """
    Mark a repository's maintainer as hostile to AI PRs.
    
    Args:
        db_path: Path to SQLite database
        repo_url: Repository URL
        reason: Reason for marking as hostile
    """
    conn = sqlite3.connect(str(db_path))
    
    try:
        conn.execute(
            """UPDATE repo_memory 
               SET maintainer_hostile = 1, notes = ?
               WHERE repo_url = ?""",
            (reason, repo_url)
        )
        conn.commit()
        logger.warning(f"Marked {repo_url} as hostile: {reason}")
        
    except Exception as e:
        logger.error(f"Failed to mark maintainer hostile: {e}")
        conn.rollback()
    finally:
        conn.close()


def get_repo_memory(db_path: Path, repo_url: str) -> Optional[RepoMemory]:
    """
    Get memory about a repository.
    
    Args:
        db_path: Path to SQLite database
        repo_url: Repository URL
    
    Returns:
        RepoMemory or None if not found
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    
    try:
        row = conn.execute(
            """SELECT repo_url, owner, repo_name, total_prs, merged_prs, rejected_prs,
                      maintainer_hostile, notes
               FROM repo_memory WHERE repo_url = ?""",
            (repo_url,)
        ).fetchone()
        
        if not row:
            return None
        
        merge_rate = row['merged_prs'] / row['total_prs'] if row['total_prs'] > 0 else 0.0
        
        return RepoMemory(
            repo_url=row['repo_url'],
            owner=row['owner'],
            repo_name=row['repo_name'],
            total_prs=row['total_prs'],
            merged_prs=row['merged_prs'],
            rejected_prs=row['rejected_prs'],
            merge_rate=merge_rate,
            maintainer_hostile=bool(row['maintainer_hostile']),
            notes=row['notes'] or ""
        )
        
    except Exception as e:
        logger.error(f"Failed to get repo memory: {e}")
        return None
    finally:
        conn.close()


# ─── Fix Patterns ─────────────────────────────────────────────────────────────

def record_fix_pattern(
    db_path: Path,
    issue_type: str,
    language: str,
    fix_approach: Dict,
    success: bool,
    confidence: float
):
    """
    Record a fix pattern and its outcome.
    
    Args:
        db_path: Path to SQLite database
        issue_type: Type of issue (e.g., "NullPointerException")
        language: Programming language
        fix_approach: Dictionary describing the fix approach
        success: True if fix was successful
        confidence: Model confidence (0-10)
    """
    conn = sqlite3.connect(str(db_path))
    
    try:
        fix_json = json.dumps(fix_approach)
        
        # Check if pattern exists
        existing = conn.execute(
            """SELECT id, success_count, failure_count, avg_confidence
               FROM fix_patterns 
               WHERE issue_type = ? AND language = ? AND fix_approach = ?""",
            (issue_type, language, fix_json)
        ).fetchone()
        
        if existing:
            # Update existing pattern
            success_count = existing[1] + (1 if success else 0)
            failure_count = existing[2] + (0 if success else 1)
            total = success_count + failure_count
            
            # Update rolling average confidence
            old_avg = existing[3]
            new_avg = (old_avg * (total - 1) + confidence) / total
            
            conn.execute(
                """UPDATE fix_patterns 
                   SET success_count = ?, failure_count = ?, avg_confidence = ?,
                       last_used = datetime('now')
                   WHERE id = ?""",
                (success_count, failure_count, new_avg, existing[0])
            )
        else:
            # Insert new pattern
            conn.execute(
                """INSERT INTO fix_patterns 
                   (issue_type, language, fix_approach, success_count, failure_count, avg_confidence, last_used)
                   VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
                (issue_type, language, fix_json, 1 if success else 0, 0 if success else 1, confidence)
            )
        
        conn.commit()
        logger.info(f"Recorded fix pattern: {issue_type} ({language}) - success={success}")
        
    except Exception as e:
        logger.error(f"Failed to record fix pattern: {e}")
        conn.rollback()
    finally:
        conn.close()


def get_successful_patterns(
    db_path: Path,
    issue_type: Optional[str] = None,
    language: Optional[str] = None,
    min_success_rate: float = 0.5,
    limit: int = 10
) -> List[FixPattern]:
    """
    Get successful fix patterns.
    
    Args:
        db_path: Path to SQLite database
        issue_type: Optional filter by issue type
        language: Optional filter by language
        min_success_rate: Minimum success rate (0.0-1.0)
        limit: Maximum number of patterns to return
    
    Returns:
        List of FixPattern objects
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    
    try:
        query = """
            SELECT issue_type, language, fix_approach, success_count, failure_count, avg_confidence
            FROM fix_patterns
            WHERE (success_count + failure_count) >= 2
        """
        params = []
        
        if issue_type:
            query += " AND issue_type = ?"
            params.append(issue_type)
        
        if language:
            query += " AND language = ?"
            params.append(language)
        
        query += " ORDER BY (CAST(success_count AS REAL) / (success_count + failure_count)) DESC, success_count DESC LIMIT ?"
        params.append(limit)
        
        rows = conn.execute(query, params).fetchall()
        
        patterns = []
        for row in rows:
            total = row['success_count'] + row['failure_count']
            success_rate = row['success_count'] / total if total > 0 else 0.0
            
            if success_rate >= min_success_rate:
                patterns.append(FixPattern(
                    issue_type=row['issue_type'],
                    language=row['language'],
                    fix_approach=json.loads(row['fix_approach']),
                    success_count=row['success_count'],
                    failure_count=row['failure_count'],
                    success_rate=success_rate,
                    avg_confidence=row['avg_confidence']
                ))
        
        return patterns
        
    except Exception as e:
        logger.error(f"Failed to get successful patterns: {e}")
        return []
    finally:
        conn.close()


# ─── Maintainer Feedback ──────────────────────────────────────────────────────

def record_feedback(
    db_path: Path,
    pr_url: str,
    repo_url: str,
    feedback_type: str,
    feedback_text: str,
    sentiment: Optional[str] = None,
    opportunity_id: Optional[int] = None
):
    """
    Record maintainer feedback on a PR.
    
    Args:
        db_path: Path to SQLite database
        pr_url: Pull request URL
        repo_url: Repository URL
        feedback_type: Type of feedback ("comment", "review", "merge", "close")
        feedback_text: The feedback text
        sentiment: Optional sentiment ("positive", "neutral", "negative")
        opportunity_id: Optional opportunity ID
    """
    conn = sqlite3.connect(str(db_path))
    
    try:
        # Extract lessons (simple keyword extraction for now)
        lessons = extract_lessons(feedback_text)
        lessons_json = json.dumps(lessons)
        
        conn.execute(
            """INSERT INTO maintainer_feedback 
               (opportunity_id, pr_url, repo_url, feedback_type, sentiment, feedback_text, extracted_lessons)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (opportunity_id, pr_url, repo_url, feedback_type, sentiment or "neutral", feedback_text, lessons_json)
        )
        
        conn.commit()
        logger.info(f"Recorded feedback for {pr_url}: {feedback_type}")
        
    except Exception as e:
        logger.error(f"Failed to record feedback: {e}")
        conn.rollback()
    finally:
        conn.close()


def extract_lessons(feedback_text: str) -> List[str]:
    """
    Extract lessons from maintainer feedback.
    
    Args:
        feedback_text: Feedback text
    
    Returns:
        List of extracted lessons
    """
    lessons = []
    text_lower = feedback_text.lower()
    
    # Common feedback patterns
    patterns = {
        "tests": ["add tests", "missing tests", "test coverage", "needs tests"],
        "documentation": ["add docs", "missing documentation", "update readme"],
        "breaking_change": ["breaking change", "breaks compatibility", "api change"],
        "style": ["code style", "formatting", "linting", "pep 8", "eslint"],
        "scope": ["too broad", "too many changes", "separate pr", "split this"],
        "explanation": ["explain", "why", "rationale", "reasoning"],
    }
    
    for category, keywords in patterns.items():
        if any(kw in text_lower for kw in keywords):
            lessons.append(category)
    
    return lessons


# ─── Success Metrics ──────────────────────────────────────────────────────────

def update_metric(db_path: Path, metric_name: str, metric_value: float):
    """
    Update a success metric.
    
    Args:
        db_path: Path to SQLite database
        metric_name: Name of the metric
        metric_value: Value of the metric
    """
    conn = sqlite3.connect(str(db_path))
    
    try:
        conn.execute(
            """INSERT OR REPLACE INTO success_metrics (metric_name, metric_value, last_updated)
               VALUES (?, ?, datetime('now'))""",
            (metric_name, metric_value)
        )
        conn.commit()
        
    except Exception as e:
        logger.error(f"Failed to update metric: {e}")
        conn.rollback()
    finally:
        conn.close()


def get_metrics(db_path: Path) -> Dict[str, float]:
    """
    Get all success metrics.
    
    Args:
        db_path: Path to SQLite database
    
    Returns:
        Dictionary of metric_name -> metric_value
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    
    try:
        rows = conn.execute("SELECT metric_name, metric_value FROM success_metrics").fetchall()
        return {row['metric_name']: row['metric_value'] for row in rows}
        
    except Exception as e:
        logger.error(f"Failed to get metrics: {e}")
        return {}
    finally:
        conn.close()


# ─── Learning Insights ────────────────────────────────────────────────────────

def get_learning_insights(db_path: Path) -> Dict:
    """
    Get insights from learning data.
    
    Args:
        db_path: Path to SQLite database
    
    Returns:
        Dictionary with insights
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    
    try:
        insights = {}
        
        # Top performing repos
        top_repos = conn.execute(
            """SELECT repo_url, owner, repo_name, merged_prs, total_prs
               FROM repo_memory
               WHERE total_prs >= 2
               ORDER BY (CAST(merged_prs AS REAL) / total_prs) DESC
               LIMIT 5"""
        ).fetchall()
        insights['top_repos'] = [dict(r) for r in top_repos]
        
        # Hostile repos
        hostile = conn.execute(
            """SELECT repo_url, owner, repo_name, notes
               FROM repo_memory
               WHERE maintainer_hostile = 1"""
        ).fetchall()
        insights['hostile_repos'] = [dict(r) for r in hostile]
        
        # Most successful fix patterns
        patterns = conn.execute(
            """SELECT issue_type, language, success_count, failure_count
               FROM fix_patterns
               WHERE (success_count + failure_count) >= 3
               ORDER BY (CAST(success_count AS REAL) / (success_count + failure_count)) DESC
               LIMIT 5"""
        ).fetchall()
        insights['top_patterns'] = [dict(r) for r in patterns]
        
        # Common feedback themes
        feedback = conn.execute(
            """SELECT extracted_lessons
               FROM maintainer_feedback
               WHERE extracted_lessons != '[]'
               LIMIT 100"""
        ).fetchall()
        
        all_lessons = []
        for row in feedback:
            all_lessons.extend(json.loads(row['extracted_lessons']))
        
        # Count lesson frequency
        from collections import Counter
        lesson_counts = Counter(all_lessons)
        insights['common_feedback'] = dict(lesson_counts.most_common(10))
        
        return insights
        
    except Exception as e:
        logger.error(f"Failed to get learning insights: {e}")
        return {}
    finally:
        conn.close()
