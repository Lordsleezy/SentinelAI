"""
Validation for SentinelAI persistent orchestration runtime.
"""

import time

import db
import queue_manager as qm
import orchestration as orch
from orchestration.models import WorkflowStatus


def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    print("SentinelAI Orchestration Runtime Validation")
    print("=" * 60)

    db.init_db()
    qm.initialize_queue()
    orchestrator = orch.initialize_orchestration()

    print("[1/7] Runtime initializes")
    status = orchestrator.status()
    assert_true(status["initialized"], "orchestrator did not initialize")
    assert_true("ResearchAgent" in status["agents"], "ResearchAgent missing")
    assert_true("DeploymentAgent" in status["agents"], "DeploymentAgent missing")
    print("  OK")

    print("[2/7] Non-approval workflow completes")
    result = orchestrator.submit_workflow(
        goal=f"orchestration smoke coding task {time.time()}",
        workflow_type="coding",
        requires_approval=False,
        enqueue=False,
    )
    workflow_id = result["workflow_id"]
    final_state = orchestrator.run_workflow(workflow_id)
    assert_true(final_state["status"] == WorkflowStatus.COMPLETED.value, "workflow did not complete")
    assert_true(final_state["assigned_agent"] == "CodingAgent", "workflow did not route to CodingAgent")
    assert_true(final_state["result"]["agent"] == "CodingAgent", "agent result missing")
    print("  OK")

    print("[3/7] Approval checkpoint pauses workflow")
    result = orchestrator.submit_workflow(
        goal=f"orchestration approval deployment task {time.time()}",
        workflow_type="deployment",
        requires_approval=True,
        enqueue=False,
    )
    approval_id = result["workflow_id"]
    waiting_state = orchestrator.run_workflow(approval_id)
    assert_true(
        waiting_state["status"] == WorkflowStatus.AWAITING_APPROVAL.value,
        "workflow did not wait for approval",
    )
    pending = orchestrator.pending_approvals()
    assert_true(any(item["workflow_id"] == approval_id for item in pending), "approval not recorded")
    print("  OK")

    print("[4/7] Approved workflow resumes and completes")
    approved_state = orchestrator.approve_workflow(approval_id, decided_by="test")
    assert_true(approved_state["approval_status"] == "approved", "approval not applied")
    completed_state = orchestrator.run_workflow(approval_id)
    assert_true(completed_state["status"] == WorkflowStatus.COMPLETED.value, "approved workflow did not complete")
    assert_true(completed_state["assigned_agent"] == "DeploymentAgent", "workflow did not route to DeploymentAgent")
    print("  OK")

    print("[5/7] Queue task handler executes workflow")
    queued = orchestrator.submit_workflow(
        goal=f"orchestration queue monitoring task {time.time()}",
        workflow_type="monitoring",
        requires_approval=False,
        enqueue=True,
    )
    task = qm.dequeue_task("orchestration_test_worker", ["orchestration_workflow"])
    assert_true(task is not None, "queued orchestration task not found")
    handled_state = orchestrator.handle_queue_task(task)
    qm.complete_task(task["id"], success=True)
    assert_true(handled_state["status"] == WorkflowStatus.COMPLETED.value, "queued workflow did not complete")
    assert_true(handled_state["assigned_agent"] == "MonitoringAgent", "workflow did not route to MonitoringAgent")
    print("  OK")

    print("[6/7] Recovery requeues interrupted workflow")
    recoverable = orchestrator.submit_workflow(
        goal=f"orchestration recovery research task {time.time()}",
        workflow_type="research",
        requires_approval=False,
        enqueue=False,
    )
    state = orchestrator.get_workflow(recoverable["workflow_id"])
    assert_true(state is not None, "recoverable workflow missing")
    # Mark as running through the public state loader/save path.
    from orchestration import persistence

    loaded = persistence.load_workflow_state(recoverable["workflow_id"])
    loaded.status = WorkflowStatus.RUNNING.value
    persistence.save_workflow_state(loaded)
    recovered = orchestrator.recover_workflows()
    assert_true(recovered >= 1, "running workflow was not recovered")
    print("  OK")

    print("[7/7] Persistent checkpoints exist")
    latest = persistence.latest_checkpoint(workflow_id)
    assert_true(latest is not None, "checkpoint missing")
    assert_true(latest["workflow_id"] == workflow_id, "checkpoint workflow id mismatch")
    print("  OK")

    print("\nALL ORCHESTRATION TESTS PASSED")


if __name__ == "__main__":
    main()
