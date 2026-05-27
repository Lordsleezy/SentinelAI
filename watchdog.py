"""
watchdog.py — Watchdog & Recovery System for SentinelAI (Phase 7)
Monitors system health, detects failures, and performs automatic recovery
"""
import threading
import time
import logging
from typing import Dict, List
from datetime import datetime
import os

import queue_manager as qm
import worker_manager as wm
import db

logger = logging.getLogger(__name__)


# ─── Watchdog Class ───────────────────────────────────────────────────────────

class Watchdog:
    """Monitors system health and performs recovery actions."""
    
    def __init__(self, check_interval: int = 30):
        self.check_interval = check_interval  # seconds
        self.running = False
        self.thread = None
        self.recovery_count = 0
        self.last_check = None
        
    def start(self):
        """Start the watchdog."""
        if self.thread and self.thread.is_alive():
            logger.warning("Watchdog already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info(f"Watchdog started (check_interval={self.check_interval}s)")
    
    def stop(self):
        """Stop the watchdog."""
        self.running = False
        logger.info("Watchdog stopped")
    
    def _run(self):
        """Main watchdog loop."""
        while self.running:
            try:
                self.last_check = datetime.now()
                
                # Check worker health
                self._check_workers()
                
                # Check for stale tasks
                self._check_stale_tasks()
                
                # Check database health
                self._check_database()
                
                # Check Ollama health
                self._check_ollama()
                
                # Sleep until next check
                time.sleep(self.check_interval)
                
            except Exception as e:
                logger.exception(f"Watchdog error: {e}")
                time.sleep(self.check_interval)
    
    def _check_workers(self):
        """Check worker health and restart unhealthy workers."""
        try:
            manager = wm.get_manager()
            unhealthy = manager.check_health()
            
            if unhealthy:
                logger.warning(f"Found {len(unhealthy)} unhealthy workers: {unhealthy}")
                
                for worker_id in unhealthy:
                    logger.info(f"Attempting to restart unhealthy worker: {worker_id}")
                    try:
                        manager.restart_worker(worker_id)
                        self.recovery_count += 1
                        db.log_event("watchdog_recovery", f"Restarted worker {worker_id}")
                    except Exception as e:
                        logger.error(f"Failed to restart worker {worker_id}: {e}")
        
        except Exception as e:
            logger.error(f"Worker health check failed: {e}")
    
    def _check_stale_tasks(self, timeout_minutes: int = 30):
        """Check for and reset stale tasks."""
        try:
            stale_tasks = qm.get_stale_tasks(timeout_minutes)
            
            if stale_tasks:
                logger.warning(f"Found {len(stale_tasks)} stale tasks")
                
                reset_count = qm.reset_stale_tasks(timeout_minutes)
                if reset_count > 0:
                    logger.info(f"Reset {reset_count} stale tasks")
                    self.recovery_count += reset_count
                    db.log_event("watchdog_recovery", f"Reset {reset_count} stale tasks")
        
        except Exception as e:
            logger.error(f"Stale task check failed: {e}")
    
    def _check_database(self):
        """Check database health."""
        try:
            # Simple health check - try to query
            db.get_recent_logs(limit=1)
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            db.log_event("watchdog_alert", f"Database health check failed: {e}")
    
    def _check_ollama(self):
        """Check Ollama health."""
        try:
            import httpx
            response = httpx.get('http://127.0.0.1:11434/api/tags', timeout=5)
            if response.status_code != 200:
                logger.warning(f"Ollama health check failed: status {response.status_code}")
                db.log_event("watchdog_alert", f"Ollama unhealthy: status {response.status_code}")
        except Exception as e:
            logger.warning(f"Ollama health check failed: {e}")
            # Don't log every Ollama failure - it's not critical
    
    def get_status(self) -> Dict:
        """Get watchdog status."""
        return {
            "running": self.running,
            "check_interval": self.check_interval,
            "recovery_count": self.recovery_count,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "is_alive": self.thread.is_alive() if self.thread else False
        }


# ─── Recovery Functions ───────────────────────────────────────────────────────

def recover_from_crash():
    """Recover system state after a crash/restart."""
    logger.info("Starting crash recovery...")
    
    try:
        # Reset any running tasks back to pending
        reset_count = qm.reset_stale_tasks(timeout_minutes=0)  # Reset all running tasks
        logger.info(f"Reset {reset_count} tasks from previous session")
        
        # Log recovery event
        db.log_event("system_recovery", f"Recovered from crash, reset {reset_count} tasks")
        
        return True
    
    except Exception as e:
        logger.error(f"Crash recovery failed: {e}")
        return False


def verify_system_integrity() -> Dict:
    """Verify system integrity. Returns dict with status of each component."""
    status = {}
    
    # Check database
    try:
        db.get_recent_logs(limit=1)
        status['database'] = 'ok'
    except Exception as e:
        status['database'] = f'error: {e}'
    
    # Check queue
    try:
        qm.get_queue_stats()
        status['queue'] = 'ok'
    except Exception as e:
        status['queue'] = f'error: {e}'
    
    # Check workers
    try:
        manager = wm.get_manager()
        manager.get_stats()
        status['workers'] = 'ok'
    except Exception as e:
        status['workers'] = f'error: {e}'
    
    # Check Ollama
    try:
        import httpx
        response = httpx.get('http://127.0.0.1:11434/api/tags', timeout=5)
        status['ollama'] = 'ok' if response.status_code == 200 else f'status {response.status_code}'
    except Exception as e:
        status['ollama'] = f'offline: {e}'
    
    return status


def cleanup_temp_files(max_age_days: int = 7):
    """Clean up old temporary files and workspaces."""
    logger.info(f"Cleaning up temp files older than {max_age_days} days...")
    
    # This is a placeholder - actual implementation would clean up:
    # - Old cloned repositories
    # - Stale browser sessions
    # - Failed workspace directories
    # - Old log files
    
    # For now, just clean up old queue tasks
    try:
        deleted = qm.cleanup_old_tasks(days=max_age_days)
        logger.info(f"Cleaned up {deleted} old queue tasks")
        return deleted
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        return 0


# ─── Global Watchdog Instance ─────────────────────────────────────────────────

_watchdog = None


def get_watchdog(check_interval: int = 30) -> Watchdog:
    """Get or create the global watchdog."""
    global _watchdog
    if _watchdog is None:
        _watchdog = Watchdog(check_interval)
    return _watchdog


def initialize_watchdog(check_interval: int = 30):
    """Initialize the watchdog system."""
    watchdog = get_watchdog(check_interval)
    logger.info(f"Watchdog initialized (check_interval={check_interval}s)")
    return watchdog
