"""Sentinel Vision engine — eyes, operator, and autonomous execution layer."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.sentinelvision.approval.approval_gate import ApprovalGate
from core.sentinelvision.audit import audit_log
from core.sentinelvision.goal_engine import GoalEngine
from core.sentinelvision.memory.vision_memory import VisionMemory
from core.sentinelvision.metrics.autonomy_score import AutonomyMetrics
from core.sentinelvision.multi_step.decomposer import decompose_objective
from core.sentinelvision.operator.browser.browser_operator import BrowserOperator
from core.sentinelvision.operator.desktop.desktop_operator import DesktopOperator
from core.sentinelvision.playbooks.recorder import load_playbook, save_playbook
from core.sentinelvision.planner.planner import VisionPlanner
from core.sentinelvision.planner.research import ResearchEngine
from core.sentinelvision.providers.registry import get_provider, resolve_provider
from core.sentinelvision.providers.workflows import get_workflow_runner
from core.sentinelvision.self_correction.self_correction_engine import SelfCorrectionEngine
from core.sentinelvision.types import ExecutionPlan, Goal, GoalStatus, PlanStep
from core.sentinelvision.vault.account_vault import AccountVault
from core.sentinelvision.provider_onboarding.onboarding_engine import ProviderOnboardingEngine
from core.sentinelvision.verification.verifier import VerificationEngine

logger = logging.getLogger("sentinel.vision.engine")


@dataclass
class OperatorBundle:
    browser: BrowserOperator
    desktop: DesktopOperator


class SentinelVisionEngine:
    def __init__(self, socketio: Any = None) -> None:
        self.socketio = socketio
        self.goals = GoalEngine()
        self.research_engine = ResearchEngine()
        self.planner = VisionPlanner()
        self.verifier = VerificationEngine()
        self.self_correction = SelfCorrectionEngine(max_retries=5)
        self.approval = ApprovalGate(self.goals)
        self.vault = AccountVault()
        self.memory = VisionMemory()
        self.metrics = AutonomyMetrics()
        self.workflows = get_workflow_runner()
        self.operators = OperatorBundle(BrowserOperator(), DesktopOperator())
        self.onboarding = ProviderOnboardingEngine(self)
        self._running: Dict[str, bool] = {}

    def _emit(self, goal_id: str, phase: str, message: str, level: str = "info", **extra: Any) -> None:
        self.goals.append_feed(goal_id, phase, message, level=level, artifact_path=extra.get("artifact_path"))
        if self.socketio:
            payload = {
                "goal_id": goal_id,
                "phase": phase,
                "message": message,
                "level": level,
                **extra,
            }
            try:
                self.socketio.emit("sentinelvision_event", payload)
                self.socketio.emit("sentinelscrub_event", payload)
            except Exception:
                pass

    def submit_goal(self, objective: str, *, provider_id: Optional[str] = None) -> Goal:
        if not provider_id:
            provider_id = self.onboarding.resolve_onboarding_objective(objective)
        try:
            from core.missions.mission_engine import get_mission_engine
            mission = get_mission_engine().resolve_or_create(objective)
        except Exception:
            mission = None
        subs = decompose_objective(objective)
        if subs and len(subs) > 1:
            parent = self.goals.create_goal(objective, metadata={"multi_step": True, "sub_count": len(subs)})
            self._emit(parent.goal_id, "queued", f"Multi-step objective: {len(subs)} sub-goals")
            threading.Thread(
                target=self._run_multi_step,
                args=(parent.goal_id, objective, subs),
                name=f"vision-multi-{parent.goal_id[:8]}",
                daemon=True,
            ).start()
            return parent

        goal = self.goals.create_goal(objective)
        if mission:
            try:
                from core.missions.mission_engine import get_mission_engine
                get_mission_engine().attach_vision_goal(
                    mission["mission_id"], goal.goal_id, objective,
                )
            except Exception:
                pass
        self._emit(goal.goal_id, "queued", f"Goal queued: {objective[:120]}")
        threading.Thread(
            target=self._run_pipeline,
            args=(goal.goal_id, objective, provider_id),
            name=f"vision-{goal.goal_id[:8]}",
            daemon=True,
        ).start()
        return goal

    def resume_after_approval(self, approval_id: str) -> Optional[Goal]:
        req = self.approval.get(approval_id)
        if not req or req.status != "approved":
            return None
        goal = self.goals.get(req.goal_id)
        if not goal:
            return None
        threading.Thread(
            target=self._continue_execution,
            args=(req.goal_id,),
            name=f"vision-resume-{req.goal_id[:8]}",
            daemon=True,
        ).start()
        return goal

    def _run_multi_step(self, parent_id: str, objective: str, subs) -> None:
        self._running[parent_id] = True
        try:
            for spec in sorted(subs, key=lambda s: s.order):
                self._emit(parent_id, "executing", f"Sub-goal {spec.order}: {spec.objective[:80]}")
                child = self.goals.create_goal(spec.objective, metadata={"parent_goal_id": parent_id, "order": spec.order})
                try:
                    self._pipeline_once(child.goal_id, spec.objective, spec.provider_id, attempt=0)
                except Exception as exc:
                    self._emit(parent_id, "failed", f"Sub-goal failed: {exc}", level="error")
                    self.goals.set_status(parent_id, GoalStatus.FAILED, error=str(exc))
                    return
            self.goals.set_status(parent_id, GoalStatus.COMPLETED)
            self._emit(parent_id, "completed", "All sub-goals completed")
            self.metrics.record("complete", True, goal_id=parent_id)
        finally:
            self._running.pop(parent_id, None)

    def _run_pipeline(self, goal_id: str, objective: str, provider_id: Optional[str]) -> None:
        if self._running.get(goal_id):
            return
        self._running[goal_id] = True
        attempt = 0
        last_terminal: Optional[Dict[str, Any]] = None
        try:
            while self.self_correction.should_retry(attempt):
                try:
                    self._pipeline_once(goal_id, objective, provider_id, attempt)
                    break
                except Exception as exc:
                    attempt += 1
                    correction = self.self_correction.run_correction_cycle(
                        goal_id, objective, provider_id or "general", exc,
                        browser=self.operators.browser,
                        desktop=self.operators.desktop,
                        last_terminal=last_terminal,
                        emit=lambda gid, ph, msg, lvl: self._emit(gid, ph, msg, lvl),
                    )
                    self.metrics.record("repair", correction.get("repaired", False), provider=provider_id or "", goal_id=goal_id)
                    if not correction.get("retry") or not self.self_correction.should_retry(attempt):
                        self.goals.set_status(goal_id, GoalStatus.FAILED, error=str(exc))
                        self._emit(goal_id, "failed", str(exc), level="error")
                        try:
                            from core.missions.mission_engine import get_mission_engine
                            get_mission_engine().on_vision_goal_completed(goal_id, objective, False)
                        except Exception:
                            pass
                        self.memory.record_workflow(provider_id or "unknown", objective, success=False, plan_summary=str(exc))
                        self.metrics.record("complete", False, provider=provider_id or "", goal_id=goal_id)
                        break
                    self._emit(goal_id, "repairing", "Retrying after self-correction…", "info")
        finally:
            self._running.pop(goal_id, None)
            try:
                self.operators.browser.close()
            except Exception:
                pass

    def _pipeline_once(self, goal_id: str, objective: str, provider_id: Optional[str], attempt: int) -> None:
        provider = get_provider(provider_id) if provider_id else resolve_provider(objective)
        pid = provider.provider_id if provider else "general"

        playbook = load_playbook(pid, objective)
        if playbook and attempt == 0:
            self._emit(goal_id, "planning", "Reusing saved playbook")

        self.goals.set_status(goal_id, GoalStatus.RESEARCHING, provider_id=pid)
        self._emit(goal_id, "researching", "Researching requirements…")
        research = playbook.get("research_summary") if playbook else None
        if not research:
            similar = self.memory.find_similar(objective)
            if similar:
                self._emit(goal_id, "researching", f"Found {len(similar)} similar workflow(s)")
            research = self.research_engine.research_objective(objective, pid)
        self.metrics.record("research", True, provider=pid, goal_id=goal_id)

        self.goals.set_status(goal_id, GoalStatus.PLANNING)
        self._emit(goal_id, "planning", "Building execution plan…")
        if playbook and playbook.get("plan"):
            from core.sentinelvision.types import utc_now
            pdata = playbook["plan"]
            steps = [PlanStep(**{**s, "params": s.get("params", {})}) for s in pdata.get("steps", [])]
            plan = ExecutionPlan(
                plan_id=pdata["plan_id"],
                goal_id=goal_id,
                steps=steps,
                provider_id=pid,
                created_at=pdata.get("created_at", utc_now()),
            )
        else:
            plan = self.planner.build_plan(goal_id, objective, pid, research if isinstance(research, dict) else {"summary": research})
        self.metrics.record("plan", True, provider=pid, goal_id=goal_id)
        self.goals.set_status(goal_id, GoalStatus.PLANNING, plan_id=plan.plan_id)
        goal = self.goals.get(goal_id)
        if goal:
            goal.metadata["plan"] = plan.to_dict()
            goal.metadata["research"] = research if isinstance(research, dict) else {"summary": research}
            self.goals._save(goal)

        self.goals.set_status(goal_id, GoalStatus.EXECUTING)
        self._emit(goal_id, "executing", f"Executing {len(plan.steps)} step(s)…")
        exec_result = self._execute_plan(goal_id, plan, provider)
        if exec_result.get("awaiting_approval"):
            return
        self.metrics.record("execute", exec_result.get("ok", True), provider=pid, goal_id=goal_id)

        self.goals.set_status(goal_id, GoalStatus.VERIFYING)
        self._emit(goal_id, "verifying", "Running autonomous verification…")
        verify = self.verifier.verify_goal(objective, pid, {"execution": exec_result, "autonomous": True})
        self.metrics.record("verify", verify.get("verified", False) or verify.get("ok", False), provider=pid, goal_id=goal_id)

        if not verify.get("verified") and not verify.get("ok"):
            raise RuntimeError(verify.get("message", "Verification failed"))

        self.goals.set_status(goal_id, GoalStatus.COMPLETED)
        self._emit(goal_id, "completed", "Goal completed — verification passed")
        try:
            from core.missions.mission_engine import get_mission_engine
            from core.memory2.engine import get_memory2_engine
            get_mission_engine().on_vision_goal_completed(goal_id, objective, True)
            get_memory2_engine().remember(
                "workflow", str(plan.to_dict())[:4000],
                key=objective[:120], project_id=pid, source="vision",
            )
        except Exception:
            pass
        path = save_playbook(pid, objective, plan.to_dict(), research if isinstance(research, dict) else {"summary": research}, verification=verify)
        self._emit(goal_id, "completed", f"Playbook saved", artifact_path=path)
        self.memory.record_workflow(pid, objective, success=True, plan_summary=str(plan.to_dict())[:500], research_summary=str(research)[:500])
        self.metrics.record("complete", True, provider=pid, goal_id=goal_id)
        audit_log("goal_completed", goal_id, provider_id=pid)

    def _execute_plan(self, goal_id: str, plan: ExecutionPlan, provider) -> Dict[str, Any]:
        results = []
        for step in plan.steps:
            self._emit(goal_id, "executing", step.description)
            if self.approval.requires_approval(step.action_type) or step.requires_approval:
                req = self.approval.create_request(
                    goal_id,
                    action=step.action_type,
                    expected_result=step.description,
                    provider_id=plan.provider_id,
                    cost=step.params.get("cost"),
                    account=step.params.get("account"),
                )
                return {"awaiting_approval": True, "approval_id": req.approval_id}

            result = self._execute_step(step, plan.provider_id, provider)
            results.append(result)
            if not result.get("ok", True) and result.get("error"):
                raise RuntimeError(result.get("error"))

        return {"steps": results, "ok": True}

    def _execute_step(self, step: PlanStep, provider_id: str, provider) -> Dict[str, Any]:
        step_dict = step.to_dict()
        if step.action_type == "verify":
            return {"ok": True, "skipped": True, "note": "deferred to autonomous verification"}
        wr = self.workflows.execute_step(provider_id, step_dict, self.operators)
        if wr.get("ok"):
            return wr
        if wr.get("error") and step.action_type not in ("research_confirm",):
            return wr

        atype = step.action_type
        params = step.params or {}
        if atype == "browser_navigate":
            return self.operators.browser.open_url(params.get("url", "about:blank"))
        if atype == "desktop_command":
            return self.operators.desktop.run_command(params.get("command") or step.description)
        if provider:
            return provider.execute(step_dict, self.operators)
        return wr

    def _continue_execution(self, goal_id: str) -> None:
        goal = self.goals.get(goal_id)
        if not goal or not goal.metadata.get("plan"):
            return
        plan_data = goal.metadata["plan"]
        steps = [PlanStep(**{**s, "params": s.get("params", {})}) for s in plan_data.get("steps", [])]
        plan = ExecutionPlan(
            plan_id=plan_data["plan_id"],
            goal_id=goal_id,
            steps=steps,
            provider_id=plan_data.get("provider_id", "general"),
            created_at=plan_data.get("created_at", ""),
        )
        provider = get_provider(plan.provider_id)
        try:
            exec_result = self._execute_plan(goal_id, plan, provider)
            if exec_result.get("awaiting_approval"):
                return
            self.goals.set_status(goal_id, GoalStatus.VERIFYING)
            verify = self.verifier.verify_goal(goal.objective, plan.provider_id, {"autonomous": True})
            if verify.get("verified") or verify.get("ok"):
                self.goals.set_status(goal_id, GoalStatus.COMPLETED)
                self._emit(goal_id, "completed", "Goal completed after approval")
            else:
                raise RuntimeError(verify.get("message", "Verification failed"))
        except Exception as exc:
            self.goals.set_status(goal_id, GoalStatus.FAILED, error=str(exc))
            self._emit(goal_id, "failed", str(exc), level="error")
