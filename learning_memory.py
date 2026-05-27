"""
learning_memory.py — Learning Memory System for SentinelAI (Phase 6)
Tracks patterns, learns from outcomes, adaptive scoring based on historical data
"""
import sqlite3
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from contextlib import contextmanager
import os
import json

from db import get_conn, DB_PATH, _ensure_dir


# ─── Schema Extensions ────────────────────────────────────────────────────────

def init_learning_tables():
    """Create learning memory tables if they don't exist."""
    _ensure_dir()
    with get_conn() as conn:
        conn.executescript("""
            -- Platform performance tracking
            CREATE TABLE IF NOT EXISTS platform_performance (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                platform         TEXT    NOT NULL,  -- 'github', 'algora', 'issuehunt'
                total_attempts   INTEGER DEFAULT 0,
                successful       INTEGER DEFAULT 0,
                failed           INTEGER DEFAULT 0,
                avg_complexity   REAL    DEFAULT 0,
                avg_bounty       REAL    DEFAULT 0,
                total_earnings   REAL    DEFAULT 0,
                last_updated     TEXT    DEFAULT (datetime('now')),
                UNIQUE(platform)
            );

            -- Issue pattern learning
            CREATE TABLE IF NOT EXISTS issue_patterns (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                pattern_type        TEXT    NOT NULL,  -- 'keyword', 'label', 'repo_type'
                pattern_value       TEXT    NOT NULL,
                success_count       INTEGER DEFAULT 0,
                failure_count       INTEGER DEFAULT 0,
                avg_actual_complexity REAL  DEFAULT 0,
                avg_time_to_complete  REAL  DEFAULT 0,  -- hours
                confidence_score    REAL    DEFAULT 0,  -- 0-1
                last_seen           TEXT    DEFAULT (datetime('now')),
                UNIQUE(pattern_type, pattern_value)
            );

            -- Complexity estimation learning
            CREATE TABLE IF NOT EXISTS complexity_feedback (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                opportunity_id      INTEGER NOT NULL,
                estimated_complexity REAL   NOT NULL,
                actual_complexity   REAL,  -- filled after completion
                time_spent_hours    REAL,
                success             INTEGER DEFAULT 0,  -- 1=success, 0=failure
                feedback_notes      TEXT,
                created_at          TEXT    DEFAULT (datetime('now')),
                FOREIGN KEY (opportunity_id) REFERENCES opportunities(id)
            );

            -- Adaptive scoring weights
            CREATE TABLE IF NOT EXISTS scoring_weights (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                weight_name      TEXT    NOT NULL UNIQUE,
                weight_value     REAL    NOT NULL,
                last_updated     TEXT    DEFAULT (datetime('now')),
                update_reason    TEXT
            );

            -- Learning events log
            CREATE TABLE IF NOT EXISTS learning_events (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type       TEXT    NOT NULL,  -- 'pattern_learned', 'weight_adjusted', etc.
                event_data       TEXT,  -- JSON
                confidence       REAL    DEFAULT 0,
                timestamp        TEXT    DEFAULT (datetime('now'))
            );

            -- Initialize default scoring weights if empty
            INSERT OR IGNORE INTO scoring_weights (weight_name, weight_value, update_reason)
            VALUES 
                ('bounty_weight', 1.0, 'Initial default'),
                ('complexity_weight', 1.0, 'Initial default'),
                ('platform_trust_weight', 1.0, 'Initial default'),
                ('recency_weight', 1.0, 'Initial default'),
                ('pattern_match_weight', 1.0, 'Initial default');

            -- Initialize platform performance tracking
            INSERT OR IGNORE INTO platform_performance (platform, total_attempts, successful, failed)
            VALUES 
                ('github', 0, 0, 0),
                ('algora', 0, 0, 0),
                ('issuehunt', 0, 0, 0);
        """)


# ─── Platform Performance Tracking ────────────────────────────────────────────

def update_platform_performance(platform: str, success: bool, bounty: float, complexity: float, earnings: float = 0):
    """Update platform performance metrics after an attempt."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO platform_performance (platform, total_attempts, successful, failed, avg_bounty, avg_complexity, total_earnings)
            VALUES (?, 1, ?, ?, ?, ?, ?)
            ON CONFLICT(platform) DO UPDATE SET
                total_attempts = total_attempts + 1,
                successful = successful + ?,
                failed = failed + ?,
                avg_bounty = (avg_bounty * total_attempts + ?) / (total_attempts + 1),
                avg_complexity = (avg_complexity * total_attempts + ?) / (total_attempts + 1),
                total_earnings = total_earnings + ?,
                last_updated = datetime('now')
        """, (
            platform,
            1 if success else 0,
            0 if success else 1,
            bounty,
            complexity,
            earnings,
            1 if success else 0,
            0 if success else 1,
            bounty,
            complexity,
            earnings
        ))
    
    log_learning_event(
        "platform_performance_updated",
        {"platform": platform, "success": success, "bounty": bounty, "complexity": complexity},
        confidence=1.0
    )


def get_platform_performance(platform: str) -> Optional[Dict]:
    """Get performance metrics for a specific platform."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM platform_performance WHERE platform = ?",
            (platform,)
        ).fetchone()
        return dict(row) if row else None


def get_all_platform_performance() -> List[Dict]:
    """Get performance metrics for all platforms."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM platform_performance ORDER BY total_earnings DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_platform_success_rate(platform: str) -> float:
    """Calculate success rate for a platform (0-1)."""
    perf = get_platform_performance(platform)
    if not perf or perf["total_attempts"] == 0:
        return 0.5  # Default neutral
    return perf["successful"] / perf["total_attempts"]


# ─── Issue Pattern Learning ───────────────────────────────────────────────────

def learn_pattern(pattern_type: str, pattern_value: str, success: bool, 
                  actual_complexity: float = 0, time_hours: float = 0):
    """Learn from a pattern occurrence (keyword, label, repo type, etc.)."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO issue_patterns (pattern_type, pattern_value, success_count, failure_count, avg_actual_complexity, avg_time_to_complete)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(pattern_type, pattern_value) DO UPDATE SET
                success_count = success_count + ?,
                failure_count = failure_count + ?,
                avg_actual_complexity = (avg_actual_complexity * (success_count + failure_count) + ?) / (success_count + failure_count + 1),
                avg_time_to_complete = (avg_time_to_complete * (success_count + failure_count) + ?) / (success_count + failure_count + 1),
                confidence_score = CAST(success_count AS REAL) / (success_count + failure_count + 1),
                last_seen = datetime('now')
        """, (
            pattern_type,
            pattern_value,
            1 if success else 0,
            0 if success else 1,
            actual_complexity,
            time_hours,
            1 if success else 0,
            0 if success else 1,
            actual_complexity,
            time_hours
        ))
    
    log_learning_event(
        "pattern_learned",
        {"type": pattern_type, "value": pattern_value, "success": success},
        confidence=0.7
    )


def get_pattern_confidence(pattern_type: str, pattern_value: str) -> float:
    """Get confidence score for a specific pattern (0-1)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT confidence_score FROM issue_patterns WHERE pattern_type = ? AND pattern_value = ?",
            (pattern_type, pattern_value)
        ).fetchone()
        return row["confidence_score"] if row else 0.5  # Default neutral


def get_patterns_by_type(pattern_type: str, min_confidence: float = 0.6) -> List[Dict]:
    """Get all patterns of a type with confidence above threshold."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM issue_patterns 
               WHERE pattern_type = ? AND confidence_score >= ?
               ORDER BY confidence_score DESC""",
            (pattern_type, min_confidence)
        ).fetchall()
        return [dict(r) for r in rows]


def extract_and_learn_patterns(opportunity_id: int, title: str, labels: List[str], 
                                repo_url: str, success: bool, actual_complexity: float = 0,
                                time_hours: float = 0):
    """Extract patterns from an opportunity and learn from the outcome."""
    # Learn from keywords in title
    keywords = ["typo", "doc", "test", "refactor", "bug", "feature", "security", 
                "performance", "ui", "api", "database", "lint", "formatting"]
    title_lower = title.lower()
    for keyword in keywords:
        if keyword in title_lower:
            learn_pattern("keyword", keyword, success, actual_complexity, time_hours)
    
    # Learn from labels
    for label in labels:
        learn_pattern("label", label.lower(), success, actual_complexity, time_hours)
    
    # Learn from repo type (detect from URL)
    if "python" in repo_url.lower() or "django" in repo_url.lower() or "flask" in repo_url.lower():
        learn_pattern("repo_type", "python", success, actual_complexity, time_hours)
    elif "typescript" in repo_url.lower() or "angular" in repo_url.lower():
        learn_pattern("repo_type", "typescript", success, actual_complexity, time_hours)
    elif "javascript" in repo_url.lower() or "react" in repo_url.lower() or "vue" in repo_url.lower():
        learn_pattern("repo_type", "javascript", success, actual_complexity, time_hours)


# ─── Complexity Estimation Learning ───────────────────────────────────────────

def record_complexity_estimate(opportunity_id: int, estimated_complexity: float):
    """Record initial complexity estimate for later feedback."""
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO complexity_feedback (opportunity_id, estimated_complexity)
               VALUES (?, ?)""",
            (opportunity_id, estimated_complexity)
        )


def update_complexity_feedback(opportunity_id: int, actual_complexity: float, 
                                time_spent_hours: float, success: bool, notes: str = ""):
    """Update complexity feedback after task completion."""
    with get_conn() as conn:
        conn.execute(
            """UPDATE complexity_feedback 
               SET actual_complexity = ?, time_spent_hours = ?, success = ?, feedback_notes = ?
               WHERE opportunity_id = ?""",
            (actual_complexity, time_spent_hours, 1 if success else 0, notes, opportunity_id)
        )
    
    log_learning_event(
        "complexity_feedback_updated",
        {"opportunity_id": opportunity_id, "estimated_vs_actual": f"{estimated_complexity} -> {actual_complexity}"},
        confidence=0.8
    )


def get_complexity_accuracy() -> Dict:
    """Calculate overall complexity estimation accuracy."""
    with get_conn() as conn:
        row = conn.execute("""
            SELECT 
                COUNT(*) as total,
                AVG(ABS(estimated_complexity - actual_complexity)) as avg_error,
                AVG(estimated_complexity) as avg_estimated,
                AVG(actual_complexity) as avg_actual
            FROM complexity_feedback
            WHERE actual_complexity IS NOT NULL
        """).fetchone()
        
        if row and row["total"] > 0:
            return {
                "total_samples": row["total"],
                "avg_error": round(row["avg_error"], 2),
                "avg_estimated": round(row["avg_estimated"], 2),
                "avg_actual": round(row["avg_actual"], 2),
                "accuracy_percent": round((1 - row["avg_error"] / 10) * 100, 1)  # 10 is max complexity
            }
        return {"total_samples": 0, "avg_error": 0, "accuracy_percent": 0}


def get_adaptive_complexity_adjustment(title: str, labels: List[str]) -> float:
    """Get complexity adjustment factor based on learned patterns (-2 to +2)."""
    adjustment = 0.0
    confidence_sum = 0.0
    
    # Check keyword patterns
    title_lower = title.lower()
    keywords = ["typo", "doc", "test", "refactor", "bug", "feature", "security", 
                "performance", "ui", "api", "database", "lint", "formatting"]
    
    for keyword in keywords:
        if keyword in title_lower:
            with get_conn() as conn:
                row = conn.execute(
                    """SELECT avg_actual_complexity, confidence_score 
                       FROM issue_patterns 
                       WHERE pattern_type = 'keyword' AND pattern_value = ?""",
                    (keyword,)
                ).fetchone()
                
                if row and row["confidence_score"] > 0.5:
                    # Adjust based on historical complexity for this keyword
                    pattern_complexity = row["avg_actual_complexity"]
                    confidence = row["confidence_score"]
                    
                    # If pattern shows easier than default (3.0), reduce; if harder, increase
                    adjustment += (pattern_complexity - 3.0) * confidence
                    confidence_sum += confidence
    
    # Check label patterns
    for label in labels:
        with get_conn() as conn:
            row = conn.execute(
                """SELECT avg_actual_complexity, confidence_score 
                   FROM issue_patterns 
                   WHERE pattern_type = 'label' AND pattern_value = ?""",
                (label.lower(),)
            ).fetchone()
            
            if row and row["confidence_score"] > 0.5:
                pattern_complexity = row["avg_actual_complexity"]
                confidence = row["confidence_score"]
                adjustment += (pattern_complexity - 3.0) * confidence
                confidence_sum += confidence
    
    # Normalize adjustment by confidence
    if confidence_sum > 0:
        adjustment = adjustment / confidence_sum
    
    # Cap adjustment to reasonable range
    return max(-2.0, min(2.0, adjustment))


# ─── Adaptive Scoring Weights ─────────────────────────────────────────────────

def get_scoring_weight(weight_name: str) -> float:
    """Get current value of a scoring weight."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT weight_value FROM scoring_weights WHERE weight_name = ?",
            (weight_name,)
        ).fetchone()
        return row["weight_value"] if row else 1.0


def update_scoring_weight(weight_name: str, new_value: float, reason: str = ""):
    """Update a scoring weight based on learning."""
    with get_conn() as conn:
        conn.execute(
            """UPDATE scoring_weights 
               SET weight_value = ?, last_updated = datetime('now'), update_reason = ?
               WHERE weight_name = ?""",
            (new_value, reason, weight_name)
        )
    
    log_learning_event(
        "scoring_weight_adjusted",
        {"weight": weight_name, "new_value": new_value, "reason": reason},
        confidence=0.9
    )


def get_all_scoring_weights() -> Dict[str, float]:
    """Get all current scoring weights as a dictionary."""
    with get_conn() as conn:
        rows = conn.execute("SELECT weight_name, weight_value FROM scoring_weights").fetchall()
        return {row["weight_name"]: row["weight_value"] for row in rows}


def calculate_adaptive_score(base_score: float, platform: str, title: str, 
                              labels: List[str], repo_url: str) -> float:
    """Calculate adaptive score using learned weights and patterns."""
    weights = get_all_scoring_weights()
    
    # Platform trust adjustment
    platform_success_rate = get_platform_success_rate(platform)
    platform_adjustment = (platform_success_rate - 0.5) * 2 * weights.get("platform_trust_weight", 1.0)
    
    # Pattern match adjustment
    pattern_boost = 0.0
    title_lower = title.lower()
    
    # Check for high-confidence positive patterns
    positive_patterns = get_patterns_by_type("keyword", min_confidence=0.7)
    for pattern in positive_patterns:
        if pattern["pattern_value"] in title_lower and pattern["confidence_score"] > 0.7:
            pattern_boost += 0.5 * weights.get("pattern_match_weight", 1.0)
    
    # Combine adjustments
    adaptive_score = base_score + platform_adjustment + pattern_boost
    
    return max(0.0, min(10.0, round(adaptive_score, 2)))


# ─── Learning Events Log ──────────────────────────────────────────────────────

def log_learning_event(event_type: str, event_data: Dict, confidence: float = 0.5):
    """Log a learning event for analysis."""
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO learning_events (event_type, event_data, confidence)
               VALUES (?, ?, ?)""",
            (event_type, json.dumps(event_data), confidence)
        )


def get_recent_learning_events(limit: int = 50) -> List[Dict]:
    """Get recent learning events."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM learning_events ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        ).fetchall()
        events = []
        for row in rows:
            event = dict(row)
            try:
                event["event_data"] = json.loads(event["event_data"]) if event["event_data"] else {}
            except:
                event["event_data"] = {}
            events.append(event)
        return events


# ─── Analytics & Insights ─────────────────────────────────────────────────────

def get_learning_summary() -> Dict:
    """Get comprehensive learning system summary."""
    with get_conn() as conn:
        # Platform stats
        platforms = get_all_platform_performance()
        
        # Pattern stats
        pattern_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM issue_patterns WHERE confidence_score > 0.6"
        ).fetchone()["cnt"]
        
        # Complexity accuracy
        complexity_stats = get_complexity_accuracy()
        
        # Learning events
        recent_events = conn.execute(
            "SELECT COUNT(*) as cnt FROM learning_events WHERE timestamp > datetime('now', '-7 days')"
        ).fetchone()["cnt"]
        
        # Top performing patterns
        top_patterns = conn.execute(
            """SELECT pattern_type, pattern_value, confidence_score, success_count
               FROM issue_patterns
               WHERE confidence_score > 0.7
               ORDER BY confidence_score DESC, success_count DESC
               LIMIT 10"""
        ).fetchall()
        
        return {
            "platforms": platforms,
            "high_confidence_patterns": pattern_count,
            "complexity_accuracy": complexity_stats,
            "learning_events_7d": recent_events,
            "top_patterns": [dict(p) for p in top_patterns],
            "scoring_weights": get_all_scoring_weights()
        }


def get_recommendations() -> List[str]:
    """Generate recommendations based on learned data."""
    recommendations = []
    
    # Platform recommendations
    platforms = get_all_platform_performance()
    best_platform = max(platforms, key=lambda p: p["total_earnings"] if p["total_earnings"] > 0 else 0)
    if best_platform["total_earnings"] > 0:
        recommendations.append(
            f"Focus on {best_platform['platform']} - highest earnings (${best_platform['total_earnings']:.2f})"
        )
    
    # Pattern recommendations
    top_patterns = get_patterns_by_type("keyword", min_confidence=0.8)
    if top_patterns:
        top = top_patterns[0]
        recommendations.append(
            f"Prioritize issues with '{top['pattern_value']}' keyword - {top['confidence_score']*100:.0f}% success rate"
        )
    
    # Complexity recommendations
    complexity_stats = get_complexity_accuracy()
    if complexity_stats["total_samples"] > 5 and complexity_stats["avg_error"] > 2:
        recommendations.append(
            f"Complexity estimation needs improvement - avg error: {complexity_stats['avg_error']:.1f}"
        )
    
    if not recommendations:
        recommendations.append("Collect more data to generate recommendations")
    
    return recommendations


# ─── Initialization ───────────────────────────────────────────────────────────

def initialize_learning_system():
    """Initialize the learning memory system."""
    init_learning_tables()
    log_learning_event("system_initialized", {"version": "1.0"}, confidence=1.0)
    return True
