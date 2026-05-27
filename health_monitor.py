"""
health_monitor.py — System Health Monitoring for SentinelAI (Phase 7)
Tracks CPU, RAM, queue depth, worker status, and system metrics
"""
import psutil
import threading
import time
import logging
from typing import Dict, List
from datetime import datetime, timedelta
from collections import deque
import os

import queue_manager as qm
import worker_manager as wm
import db

logger = logging.getLogger(__name__)


# ─── Health Monitor Class ─────────────────────────────────────────────────────

class HealthMonitor:
    """Monitors system health metrics."""
    
    def __init__(self, sample_interval: int = 60, history_size: int = 60):
        self.sample_interval = sample_interval  # seconds
        self.history_size = history_size  # number of samples to keep
        self.running = False
        self.thread = None
        self.started_at = None
        
        # Metric history (rolling window)
        self.cpu_history = deque(maxlen=history_size)
        self.ram_history = deque(maxlen=history_size)
        self.queue_depth_history = deque(maxlen=history_size)
        self.worker_count_history = deque(maxlen=history_size)
        
        # Thresholds
        self.cpu_warning_threshold = 80.0  # percent
        self.cpu_critical_threshold = 95.0  # percent
        self.ram_warning_threshold = 80.0  # percent
        self.ram_critical_threshold = 95.0  # percent
        self.queue_warning_threshold = 100  # tasks
        self.queue_critical_threshold = 400  # tasks
        
    def start(self):
        """Start the health monitor."""
        if self.thread and self.thread.is_alive():
            logger.warning("Health monitor already running")
            return
        
        self.running = True
        self.started_at = datetime.now()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        logger.info(f"Health monitor started (sample_interval={self.sample_interval}s)")
    
    def stop(self):
        """Stop the health monitor."""
        self.running = False
        logger.info("Health monitor stopped")
    
    def _run(self):
        """Main monitoring loop."""
        while self.running:
            try:
                # Collect metrics
                metrics = self._collect_metrics()
                
                # Store in history
                self.cpu_history.append({
                    'timestamp': metrics['timestamp'],
                    'value': metrics['cpu_percent']
                })
                self.ram_history.append({
                    'timestamp': metrics['timestamp'],
                    'value': metrics['ram_percent']
                })
                self.queue_depth_history.append({
                    'timestamp': metrics['timestamp'],
                    'value': metrics['queue_depth']
                })
                self.worker_count_history.append({
                    'timestamp': metrics['timestamp'],
                    'value': metrics['active_workers']
                })
                
                # Check thresholds and log warnings
                self._check_thresholds(metrics)
                
                # Sleep until next sample
                time.sleep(self.sample_interval)
                
            except Exception as e:
                logger.exception(f"Health monitor error: {e}")
                time.sleep(self.sample_interval)
    
    def _collect_metrics(self) -> Dict:
        """Collect current system metrics."""
        metrics = {
            'timestamp': datetime.now().isoformat()
        }
        
        # CPU usage
        try:
            metrics['cpu_percent'] = psutil.cpu_percent(interval=1)
        except:
            metrics['cpu_percent'] = 0.0
        
        # RAM usage
        try:
            mem = psutil.virtual_memory()
            metrics['ram_percent'] = mem.percent
            metrics['ram_used_mb'] = mem.used / (1024 * 1024)
            metrics['ram_total_mb'] = mem.total / (1024 * 1024)
        except:
            metrics['ram_percent'] = 0.0
            metrics['ram_used_mb'] = 0.0
            metrics['ram_total_mb'] = 0.0
        
        # Queue depth
        try:
            metrics['queue_depth'] = qm.get_queue_depth()
            queue_stats = qm.get_queue_stats()
            metrics['queue_stats'] = queue_stats
        except:
            metrics['queue_depth'] = 0
            metrics['queue_stats'] = {}
        
        # Worker status
        try:
            manager = wm.get_manager()
            worker_stats = manager.get_stats()
            metrics['active_workers'] = worker_stats.get('total_workers', 0)
            metrics['worker_stats'] = worker_stats
        except:
            metrics['active_workers'] = 0
            metrics['worker_stats'] = {}
        
        # Uptime
        if self.started_at:
            uptime = datetime.now() - self.started_at
            metrics['uptime_seconds'] = uptime.total_seconds()
        else:
            metrics['uptime_seconds'] = 0
        
        # Database stats
        try:
            earnings = db.get_earnings_summary()
            metrics['earnings'] = earnings
        except:
            metrics['earnings'] = {}
        
        return metrics
    
    def _check_thresholds(self, metrics: Dict):
        """Check metrics against thresholds and log warnings."""
        # CPU
        cpu = metrics.get('cpu_percent', 0)
        if cpu >= self.cpu_critical_threshold:
            logger.critical(f"CPU usage critical: {cpu:.1f}%")
            db.log_event("health_critical", f"CPU usage: {cpu:.1f}%")
        elif cpu >= self.cpu_warning_threshold:
            logger.warning(f"CPU usage high: {cpu:.1f}%")
        
        # RAM
        ram = metrics.get('ram_percent', 0)
        if ram >= self.ram_critical_threshold:
            logger.critical(f"RAM usage critical: {ram:.1f}%")
            db.log_event("health_critical", f"RAM usage: {ram:.1f}%")
        elif ram >= self.ram_warning_threshold:
            logger.warning(f"RAM usage high: {ram:.1f}%")
        
        # Queue depth
        queue_depth = metrics.get('queue_depth', 0)
        if queue_depth >= self.queue_critical_threshold:
            logger.critical(f"Queue depth critical: {queue_depth} tasks")
            db.log_event("health_critical", f"Queue depth: {queue_depth} tasks")
        elif queue_depth >= self.queue_warning_threshold:
            logger.warning(f"Queue depth high: {queue_depth} tasks")
    
    def get_current_metrics(self) -> Dict:
        """Get current system metrics."""
        return self._collect_metrics()
    
    def get_metrics_summary(self) -> Dict:
        """Get summary of metrics with averages and trends."""
        summary = {}
        
        # CPU summary
        if self.cpu_history:
            cpu_values = [m['value'] for m in self.cpu_history]
            summary['cpu'] = {
                'current': cpu_values[-1] if cpu_values else 0,
                'average': sum(cpu_values) / len(cpu_values),
                'max': max(cpu_values),
                'min': min(cpu_values),
                'samples': len(cpu_values)
            }
        
        # RAM summary
        if self.ram_history:
            ram_values = [m['value'] for m in self.ram_history]
            summary['ram'] = {
                'current': ram_values[-1] if ram_values else 0,
                'average': sum(ram_values) / len(ram_values),
                'max': max(ram_values),
                'min': min(ram_values),
                'samples': len(ram_values)
            }
        
        # Queue depth summary
        if self.queue_depth_history:
            queue_values = [m['value'] for m in self.queue_depth_history]
            summary['queue_depth'] = {
                'current': queue_values[-1] if queue_values else 0,
                'average': sum(queue_values) / len(queue_values),
                'max': max(queue_values),
                'min': min(queue_values),
                'samples': len(queue_values)
            }
        
        # Worker count summary
        if self.worker_count_history:
            worker_values = [m['value'] for m in self.worker_count_history]
            summary['workers'] = {
                'current': worker_values[-1] if worker_values else 0,
                'average': sum(worker_values) / len(worker_values),
                'max': max(worker_values),
                'min': min(worker_values),
                'samples': len(worker_values)
            }
        
        # Uptime
        if self.started_at:
            uptime = datetime.now() - self.started_at
            summary['uptime_seconds'] = uptime.total_seconds()
            summary['uptime_formatted'] = str(uptime).split('.')[0]  # Remove microseconds
        
        return summary
    
    def get_health_status(self) -> str:
        """Get overall health status: healthy, warning, critical."""
        metrics = self._collect_metrics()
        
        # Check for critical conditions
        if (metrics.get('cpu_percent', 0) >= self.cpu_critical_threshold or
            metrics.get('ram_percent', 0) >= self.ram_critical_threshold or
            metrics.get('queue_depth', 0) >= self.queue_critical_threshold):
            return 'critical'
        
        # Check for warning conditions
        if (metrics.get('cpu_percent', 0) >= self.cpu_warning_threshold or
            metrics.get('ram_percent', 0) >= self.ram_warning_threshold or
            metrics.get('queue_depth', 0) >= self.queue_warning_threshold):
            return 'warning'
        
        return 'healthy'
    
    def get_status(self) -> Dict:
        """Get monitor status."""
        return {
            "running": self.running,
            "sample_interval": self.sample_interval,
            "history_size": self.history_size,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "is_alive": self.thread.is_alive() if self.thread else False,
            "health_status": self.get_health_status() if self.running else "unknown"
        }


# ─── Global Monitor Instance ──────────────────────────────────────────────────

_monitor = None


def get_monitor(sample_interval: int = 60, history_size: int = 60) -> HealthMonitor:
    """Get or create the global health monitor."""
    global _monitor
    if _monitor is None:
        _monitor = HealthMonitor(sample_interval, history_size)
    return _monitor


def initialize_health_monitor(sample_interval: int = 60, history_size: int = 60):
    """Initialize the health monitoring system."""
    monitor = get_monitor(sample_interval, history_size)
    logger.info(f"Health monitor initialized (sample_interval={sample_interval}s, history_size={history_size})")
    return monitor
