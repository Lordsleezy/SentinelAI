"""
worker_manager.py — Worker Orchestration for SentinelAI (Phase 7)
Manages worker lifecycle, scheduling, concurrency limits, and health tracking
"""
import threading
import time
import logging
from typing import Dict, List, Optional, Callable
from datetime import datetime
from enum import Enum
import os

import queue_manager as qm
import db

logger = logging.getLogger(__name__)


# ─── Worker States ────────────────────────────────────────────────────────────

class WorkerState(Enum):
    IDLE = "idle"
    SCANNING = "scanning"
    QUEUED = "queued"
    EXECUTING = "executing"
    PAUSED = "paused"
    FAILED = "failed"
    STOPPED = "stopped"


# ─── Worker Class ─────────────────────────────────────────────────────────────

class Worker:
    """Represents a single worker thread."""
    
    def __init__(self, worker_id: str, task_types: List[str], handler: Callable):
        self.worker_id = worker_id
        self.task_types = task_types
        self.handler = handler
        self.state = WorkerState.IDLE
        self.current_task = None
        self.thread = None
        self.running = False
        self.paused = False
        self.last_heartbeat = datetime.now()
        self.tasks_completed = 0
        self.tasks_failed = 0
        self.started_at = None
        
    def start(self):
        """Start the worker thread."""
        if self.thread and self.thread.is_alive():
            logger.warning(f"Worker {self.worker_id} already running")
            return
        
        self.running = True
        self.paused = False
        self.started_at = datetime.now()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info(f"Worker {self.worker_id} started")
    
    def stop(self):
        """Stop the worker thread."""
        self.running = False
        self.state = WorkerState.STOPPED
        logger.info(f"Worker {self.worker_id} stopped")
    
    def pause(self):
        """Pause the worker."""
        self.paused = True
        self.state = WorkerState.PAUSED
        logger.info(f"Worker {self.worker_id} paused")
    
    def resume(self):
        """Resume the worker."""
        self.paused = False
        if self.state == WorkerState.PAUSED:
            self.state = WorkerState.IDLE
        logger.info(f"Worker {self.worker_id} resumed")
    
    def _run(self):
        """Main worker loop."""
        while self.running:
            try:
                # Update heartbeat
                self.last_heartbeat = datetime.now()
                
                # Check if paused
                if self.paused:
                    time.sleep(1)
                    continue
                
                # Try to get a task
                self.state = WorkerState.QUEUED
                task = qm.dequeue_task(self.worker_id, self.task_types)
                
                if not task:
                    # No tasks available, idle
                    self.state = WorkerState.IDLE
                    time.sleep(2)
                    continue
                
                # Execute task
                self.current_task = task
                self.state = WorkerState.EXECUTING
                logger.info(f"Worker {self.worker_id} executing task {task['id']} ({task['task_type']})")
                
                try:
                    # Call handler
                    result = self.handler(task)
                    
                    # Mark as completed
                    qm.complete_task(task['id'], success=True)
                    self.tasks_completed += 1
                    logger.info(f"Worker {self.worker_id} completed task {task['id']}")
                    
                except Exception as e:
                    # Task failed
                    error_msg = str(e)
                    logger.error(f"Worker {self.worker_id} task {task['id']} failed: {error_msg}")
                    
                    # Try to retry
                    retried = qm.retry_task(task['id'], error_msg)
                    if not retried:
                        self.tasks_failed += 1
                    
                finally:
                    self.current_task = None
                    self.state = WorkerState.IDLE
                
            except Exception as e:
                logger.exception(f"Worker {self.worker_id} error: {e}")
                self.state = WorkerState.FAILED
                time.sleep(5)  # Back off on error
    
    def get_status(self) -> Dict:
        """Get worker status."""
        return {
            "worker_id": self.worker_id,
            "state": self.state.value,
            "task_types": self.task_types,
            "current_task": self.current_task['id'] if self.current_task else None,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "is_alive": self.thread.is_alive() if self.thread else False
        }


# ─── Worker Manager ───────────────────────────────────────────────────────────

class WorkerManager:
    """Manages all workers."""
    
    def __init__(self, max_workers: int = 3):
        self.max_workers = max_workers
        self.workers: Dict[str, Worker] = {}
        self.handlers: Dict[str, Callable] = {}
        self.running = False
        self.paused = False
        
    def register_handler(self, task_type: str, handler: Callable):
        """Register a task handler function."""
        self.handlers[task_type] = handler
        logger.info(f"Registered handler for task type: {task_type}")
    
    def create_worker(self, worker_id: str, task_types: List[str]) -> Worker:
        """Create a new worker."""
        if len(self.workers) >= self.max_workers:
            raise ValueError(f"Max workers ({self.max_workers}) reached")
        
        # Get handler for first task type (workers can handle multiple types)
        handler = self._get_handler_for_types(task_types)
        
        worker = Worker(worker_id, task_types, handler)
        self.workers[worker_id] = worker
        logger.info(f"Created worker {worker_id} for task types: {task_types}")
        return worker
    
    def _get_handler_for_types(self, task_types: List[str]) -> Callable:
        """Get a unified handler that can route to specific handlers."""
        def unified_handler(task):
            task_type = task['task_type']
            if task_type in self.handlers:
                return self.handlers[task_type](task)
            else:
                raise ValueError(f"No handler registered for task type: {task_type}")
        return unified_handler
    
    def start_all(self):
        """Start all workers."""
        self.running = True
        for worker in self.workers.values():
            worker.start()
        logger.info(f"Started {len(self.workers)} workers")
    
    def stop_all(self):
        """Stop all workers."""
        self.running = False
        for worker in self.workers.values():
            worker.stop()
        logger.info("Stopped all workers")
    
    def pause_all(self):
        """Pause all workers."""
        self.paused = True
        for worker in self.workers.values():
            worker.pause()
        logger.info("Paused all workers")
    
    def resume_all(self):
        """Resume all workers."""
        self.paused = False
        for worker in self.workers.values():
            worker.resume()
        logger.info("Resumed all workers")
    
    def restart_worker(self, worker_id: str):
        """Restart a specific worker."""
        if worker_id not in self.workers:
            logger.warning(f"Worker {worker_id} not found")
            return
        
        worker = self.workers[worker_id]
        
        # Clear any running tasks
        qm.clear_worker_tasks(worker_id)
        
        # Stop and restart
        worker.stop()
        time.sleep(1)
        worker.start()
        logger.info(f"Restarted worker {worker_id}")
    
    def get_worker_status(self, worker_id: str) -> Optional[Dict]:
        """Get status of a specific worker."""
        if worker_id not in self.workers:
            return None
        return self.workers[worker_id].get_status()
    
    def get_all_worker_status(self) -> List[Dict]:
        """Get status of all workers."""
        return [worker.get_status() for worker in self.workers.values()]
    
    def get_stats(self) -> Dict:
        """Get manager statistics."""
        total_completed = sum(w.tasks_completed for w in self.workers.values())
        total_failed = sum(w.tasks_failed for w in self.workers.values())
        
        states = {}
        for worker in self.workers.values():
            state = worker.state.value
            states[state] = states.get(state, 0) + 1
        
        return {
            "total_workers": len(self.workers),
            "max_workers": self.max_workers,
            "running": self.running,
            "paused": self.paused,
            "total_completed": total_completed,
            "total_failed": total_failed,
            "worker_states": states
        }
    
    def check_health(self) -> List[str]:
        """Check health of all workers. Returns list of unhealthy worker IDs."""
        unhealthy = []
        now = datetime.now()
        
        for worker_id, worker in self.workers.items():
            # Check if thread is alive
            if worker.running and (not worker.thread or not worker.thread.is_alive()):
                unhealthy.append(worker_id)
                logger.warning(f"Worker {worker_id} thread is dead")
                continue
            
            # Check heartbeat (should be within last 60 seconds)
            if worker.running and not worker.paused:
                heartbeat_age = (now - worker.last_heartbeat).total_seconds()
                if heartbeat_age > 60:
                    unhealthy.append(worker_id)
                    logger.warning(f"Worker {worker_id} heartbeat stale ({heartbeat_age:.0f}s)")
        
        return unhealthy


# ─── Global Manager Instance ──────────────────────────────────────────────────

_manager = None


def get_manager(max_workers: int = 3) -> WorkerManager:
    """Get or create the global worker manager."""
    global _manager
    if _manager is None:
        _manager = WorkerManager(max_workers)
    return _manager


def initialize_workers(max_workers: int = 3):
    """Initialize the worker management system."""
    manager = get_manager(max_workers)
    logger.info(f"Worker manager initialized (max_workers={max_workers})")
    return manager
