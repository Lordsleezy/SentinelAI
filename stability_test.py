"""
stability_test.py — Long-Duration Stability Test for Phase 8
Tests system stability under continuous operation
"""
import time
import psutil
import threading
from datetime import datetime, timedelta

import db
import queue_manager as qm
import worker_manager as wm
import watchdog as wd
import health_monitor as hm

print("=" * 80)
print("PHASE 8: LONG-DURATION STABILITY TEST")
print("=" * 80)
print("\nThis test will run for 5 minutes to validate system stability.")
print("Monitoring: memory usage, CPU, queue operations, worker health")
print("\nPress Ctrl+C to stop early if needed.\n")

# Configuration
TEST_DURATION_MINUTES = 5
TASK_INTERVAL_SECONDS = 2
METRICS_INTERVAL_SECONDS = 10

# Initialize systems
print("[INIT] Initializing systems...")
db.init_db()
qm.initialize_queue()
manager = wm.initialize_workers(max_workers=2)
watchdog = wd.initialize_watchdog(check_interval=15)
monitor = hm.initialize_health_monitor(sample_interval=10, history_size=100)

# Start monitoring systems
watchdog.start()
monitor.start()

# Metrics tracking
start_time = datetime.now()
end_time = start_time + timedelta(minutes=TEST_DURATION_MINUTES)
metrics_history = []
task_count = 0
completed_count = 0
failed_count = 0

# Task handler
def stability_task_handler(task):
    """Simple task handler for stability testing."""
    time.sleep(0.1)  # Simulate work
    return True

# Register handler and create worker
manager.register_handler("stability_test", stability_task_handler)
worker = manager.create_worker("stability_worker_1", ["stability_test"])
worker.start()

print(f"[START] Test started at {start_time.strftime('%H:%M:%S')}")
print(f"[TARGET] Will run until {end_time.strftime('%H:%M:%S')}")
print("-" * 80)

try:
    last_metrics_time = datetime.now()
    last_task_time = datetime.now()
    
    while datetime.now() < end_time:
        current_time = datetime.now()
        
        # Enqueue tasks periodically
        if (current_time - last_task_time).total_seconds() >= TASK_INTERVAL_SECONDS:
            task_id = qm.enqueue_task(
                "stability_test",
                priority=5,
                task_data={"iteration": task_count}
            )
            task_count += 1
            last_task_time = current_time
        
        # Collect metrics periodically
        if (current_time - last_metrics_time).total_seconds() >= METRICS_INTERVAL_SECONDS:
            # Get current metrics
            process = psutil.Process()
            memory_mb = process.memory_info().rss / (1024 * 1024)
            cpu_percent = process.cpu_percent(interval=0.1)
            
            queue_stats = qm.get_queue_stats()
            worker_stats = manager.get_stats()
            health_metrics = monitor.get_current_metrics()
            
            # Track completed/failed
            completed_count = queue_stats.get('completed_count', 0)
            failed_count = queue_stats.get('failed_count', 0)
            
            # Store metrics
            metrics_history.append({
                'timestamp': current_time,
                'memory_mb': memory_mb,
                'cpu_percent': cpu_percent,
                'queue_pending': queue_stats.get('pending_count', 0),
                'queue_running': queue_stats.get('running_count', 0),
                'tasks_completed': completed_count,
                'tasks_failed': failed_count,
                'worker_count': worker_stats.get('total_workers', 0)
            })
            
            # Print status
            elapsed = (current_time - start_time).total_seconds()
            remaining = (end_time - current_time).total_seconds()
            
            print(f"[{int(elapsed)}s] "
                  f"Memory: {memory_mb:.1f}MB | "
                  f"CPU: {cpu_percent:.1f}% | "
                  f"Queue: {queue_stats.get('pending_count', 0)}P/{queue_stats.get('running_count', 0)}R | "
                  f"Tasks: {task_count}E/{completed_count}C/{failed_count}F | "
                  f"Remaining: {int(remaining)}s")
            
            last_metrics_time = current_time
        
        # Small sleep to prevent busy loop
        time.sleep(0.5)

except KeyboardInterrupt:
    print("\n[INTERRUPTED] Test stopped by user")

# Stop systems
print("\n[STOP] Stopping systems...")
worker.stop()
manager.stop_all()
watchdog.stop()
monitor.stop()

# Wait for worker to finish
time.sleep(2)

# Final metrics
print("\n" + "=" * 80)
print("STABILITY TEST RESULTS")
print("=" * 80)

final_time = datetime.now()
total_duration = (final_time - start_time).total_seconds()

print(f"\nTest Duration: {total_duration:.1f} seconds ({total_duration/60:.1f} minutes)")
print(f"Tasks Enqueued: {task_count}")
print(f"Tasks Completed: {completed_count}")
print(f"Tasks Failed: {failed_count}")
print(f"Success Rate: {(completed_count/task_count*100) if task_count > 0 else 0:.1f}%")

# Memory analysis
if metrics_history:
    memory_values = [m['memory_mb'] for m in metrics_history]
    memory_start = memory_values[0]
    memory_end = memory_values[-1]
    memory_max = max(memory_values)
    memory_growth = memory_end - memory_start
    
    print(f"\nMemory Usage:")
    print(f"  Start: {memory_start:.1f} MB")
    print(f"  End: {memory_end:.1f} MB")
    print(f"  Peak: {memory_max:.1f} MB")
    print(f"  Growth: {memory_growth:+.1f} MB ({(memory_growth/memory_start*100):+.1f}%)")
    
    # CPU analysis
    cpu_values = [m['cpu_percent'] for m in metrics_history]
    cpu_avg = sum(cpu_values) / len(cpu_values)
    cpu_max = max(cpu_values)
    
    print(f"\nCPU Usage:")
    print(f"  Average: {cpu_avg:.1f}%")
    print(f"  Peak: {cpu_max:.1f}%")
    
    # Queue analysis
    queue_pending = [m['queue_pending'] for m in metrics_history]
    queue_avg = sum(queue_pending) / len(queue_pending)
    queue_max = max(queue_pending)
    
    print(f"\nQueue Depth:")
    print(f"  Average Pending: {queue_avg:.1f}")
    print(f"  Peak Pending: {queue_max}")

# Health check
print(f"\nFinal Health Status:")
integrity = wd.verify_system_integrity()
for component, status in integrity.items():
    print(f"  {component}: {status}")

# Warnings
print(f"\nWarnings:")
warnings = []

if metrics_history:
    # Check for memory leak (>10% growth)
    if memory_growth > memory_start * 0.1:
        warnings.append(f"⚠️  Possible memory leak detected ({memory_growth:+.1f} MB growth)")
    
    # Check for high CPU
    if cpu_avg > 50:
        warnings.append(f"⚠️  High average CPU usage ({cpu_avg:.1f}%)")
    
    # Check for queue backup
    if queue_max > 50:
        warnings.append(f"⚠️  Queue backup detected (peak: {queue_max} tasks)")
    
    # Check for failures
    if failed_count > 0:
        warnings.append(f"⚠️  {failed_count} task failures detected")

if not warnings:
    print("  ✅ No warnings - system stable")
else:
    for warning in warnings:
        print(f"  {warning}")

# Cleanup
print(f"\n[CLEANUP] Cleaning up test data...")
qm.cleanup_old_tasks(days=0)

print("\n" + "=" * 80)
if not warnings and completed_count > 0:
    print("✅ STABILITY TEST PASSED")
    print("System demonstrated stable operation under continuous load.")
else:
    print("⚠️  STABILITY TEST COMPLETED WITH WARNINGS")
    print("Review warnings above for potential issues.")
print("=" * 80)
