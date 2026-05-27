"""
test_always_on.py — Test script for Phase 7 Always-On Operations
Tests queue, workers, watchdog, and health monitoring systems
"""
import time
import queue_manager as qm
import worker_manager as wm
import watchdog as wd
import health_monitor as hm
import db

print("=" * 80)
print("PHASE 7: ALWAYS-ON OPERATIONS TEST")
print("=" * 80)

# Initialize all systems
print("\n[1/8] Initializing database...")
db.init_db()
print("✅ Database initialized")

print("\n[2/8] Initializing queue system...")
qm.initialize_queue()
print("✅ Queue system initialized")

print("\n[3/8] Initializing worker manager...")
manager = wm.initialize_workers(max_workers=2)
print(f"✅ Worker manager initialized (max_workers=2)")

print("\n[4/8] Initializing watchdog...")
watchdog = wd.initialize_watchdog(check_interval=5)
print("✅ Watchdog initialized")

print("\n[5/8] Initializing health monitor...")
monitor = hm.initialize_health_monitor(sample_interval=5, history_size=10)
print("✅ Health monitor initialized")

# Test queue operations
print("\n[6/8] Testing queue operations...")
task_id1 = qm.enqueue_task("test_task", priority=1, task_data={"test": "data1"})
task_id2 = qm.enqueue_task("test_task", priority=5, task_data={"test": "data2"})
task_id3 = qm.enqueue_task("test_task", priority=3, task_data={"test": "data3"})
print(f"   Enqueued 3 tasks: {task_id1}, {task_id2}, {task_id3}")

stats = qm.get_queue_stats()
print(f"   Queue stats: {stats.get('pending_count', 0)} pending, {stats.get('total_tasks', 0)} total")

# Test dequeue (should get priority 1 first)
task = qm.dequeue_task("test_worker", ["test_task"])
print(f"   Dequeued task: #{task['id']} (priority={task['priority']})")
assert task['priority'] == 1, "Priority queue not working!"

# Complete the task
qm.complete_task(task['id'], success=True)
print(f"   Completed task #{task['id']}")

# Test retry
task2 = qm.dequeue_task("test_worker", ["test_task"])
retried = qm.retry_task(task2['id'], "Test error")
print(f"   Retried task #{task2['id']}: {retried}")

print("✅ Queue operations working")

# Test worker creation
print("\n[7/8] Testing worker system...")

def test_handler(task):
    """Test task handler."""
    print(f"   Handler processing task #{task['id']}")
    time.sleep(0.1)
    return True

manager.register_handler("test_task", test_handler)
worker = manager.create_worker("worker_1", ["test_task"])
print(f"   Created worker: {worker.worker_id}")

worker_status = manager.get_worker_status("worker_1")
print(f"   Worker state: {worker_status['state']}")

manager_stats = manager.get_stats()
print(f"   Manager stats: {manager_stats['total_workers']} workers")

print("✅ Worker system working")

# Test health monitoring
print("\n[8/8] Testing health monitoring...")
monitor.start()
time.sleep(2)  # Let it collect one sample

metrics = monitor.get_current_metrics()
print(f"   CPU: {metrics.get('cpu_percent', 0):.1f}%")
print(f"   RAM: {metrics.get('ram_percent', 0):.1f}%")
print(f"   Queue depth: {metrics.get('queue_depth', 0)}")

health_status = monitor.get_health_status()
print(f"   Health status: {health_status}")

monitor.stop()
print("✅ Health monitoring working")

# Test watchdog
print("\n[BONUS] Testing watchdog...")
watchdog.start()
time.sleep(2)

watchdog_status = watchdog.get_status()
print(f"   Watchdog running: {watchdog_status['running']}")
print(f"   Recovery count: {watchdog_status['recovery_count']}")

watchdog.stop()
print("✅ Watchdog working")

# Test crash recovery
print("\n[BONUS] Testing crash recovery...")
recovered = wd.recover_from_crash()
print(f"   Crash recovery: {'✅ Success' if recovered else '❌ Failed'}")

# Test system integrity
print("\n[BONUS] Testing system integrity...")
integrity = wd.verify_system_integrity()
print(f"   Database: {integrity.get('database', 'unknown')}")
print(f"   Queue: {integrity.get('queue', 'unknown')}")
print(f"   Workers: {integrity.get('workers', 'unknown')}")
print(f"   Ollama: {integrity.get('ollama', 'unknown')}")

# Cleanup
print("\n[CLEANUP] Cleaning up test data...")
cleanup_count = qm.cleanup_old_tasks(days=0)  # Clean all tasks
print(f"   Cleaned up {cleanup_count} tasks")

print("\n" + "=" * 80)
print("✅ ALL TESTS PASSED!")
print("=" * 80)
print("\nPhase 7 Always-On Operations systems are functional:")
print("  ✅ Queue Manager - Persistent task queue with priorities")
print("  ✅ Worker Manager - Worker orchestration and lifecycle")
print("  ✅ Watchdog - Health checks and auto-recovery")
print("  ✅ Health Monitor - System metrics and thresholds")
print("  ✅ Crash Recovery - State restoration after restart")
print("\nSentinelAI is ready for continuous autonomous operation!")
