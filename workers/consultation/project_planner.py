"""Project Planner — autonomous multi-file project generation.

Phase 1: Consult Claude + ChatGPT for architecture → merge with Ollama.
Phase 2: Feed tasks to Forge in dependency order.
Phase 3: Handle stuck tasks via Consultant.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:14b")
BACKEND_URL = "http://127.0.0.1:5001"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Task:
    id: int
    description: str
    depends_on: List[int] = field(default_factory=list)
    status: str = "pending"   # pending | running | complete | failed
    attempts: int = 0
    result: Optional[str] = None


@dataclass
class ProjectPlan:
    intent: str
    stack: List[str]
    files: List[str]
    tasks: List[Task]
    pitfalls: List[str]
    claude_input: str
    gpt_input: str
    created_at: str
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


@dataclass
class ExecutionResult:
    success: bool
    completed_tasks: int
    failed_tasks: int
    log: List[str]


# ---------------------------------------------------------------------------
# In-memory plan registry
# ---------------------------------------------------------------------------

_plans: Dict[str, ProjectPlan] = {}
_plan_status: Dict[str, dict] = {}    # plan_id -> {status, log, current_task}


def get_plan(plan_id: str) -> Optional[ProjectPlan]:
    return _plans.get(plan_id)


def all_plan_ids() -> list:
    return list(_plans.keys())


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

class ProjectPlanner:
    def __init__(self):
        from workers.consultation.consultant import get_consultant
        self.consultant = get_consultant()

    def _ask_ollama(self, prompt: str, timeout: int = 90) -> Optional[str]:
        try:
            resp = httpx.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
                timeout=timeout,
            )
            if resp.status_code == 200:
                return resp.json().get("response", "").strip()
        except Exception as exc:
            logger.debug("[Planner] Ollama error: %s", exc)
        return None

    def plan_project(self, user_intent: str) -> ProjectPlan:
        """Phase 1: consult Claude + ChatGPT, merge with Ollama."""
        arch_prompt = (
            f"Design the architecture for: {user_intent}\n\n"
            "Include: tech stack, file structure, implementation order, "
            "potential pitfalls. Be specific and practical. Keep it concise."
        )

        logger.info("[Planner] Consulting ChatGPT for architecture...")
        gpt_resp = self.consultant.ask_chatgpt(arch_prompt) or ""

        logger.info("[Planner] Consulting Claude for architecture...")
        claude_resp = self.consultant.ask_claude(arch_prompt) or ""

        plan = self.merge_plans(claude_resp, gpt_resp, user_intent)
        _plans[plan.id] = plan
        _plan_status[plan.id] = {
            "status": "awaiting_approval",
            "current_task": 0,
            "total_tasks": len(plan.tasks),
            "log": [f"Plan created: {len(plan.tasks)} tasks"],
        }
        return plan

    def merge_plans(self, claude_response: str, gpt_response: str, intent: str) -> ProjectPlan:
        merge_prompt = (
            f"You received two architecture proposals for: {intent}\n\n"
            f"Proposal A (Claude): {claude_response or 'N/A'}\n\n"
            f"Proposal B (GPT): {gpt_response or 'N/A'}\n\n"
            "Merge the best ideas from both into a single clear plan. "
            "Output ONLY valid JSON:\n"
            '{"stack": ["..."], "files": ["..."], '
            '"tasks": [{"id": 1, "description": "...", "depends_on": []}], '
            '"pitfalls": ["..."]}'
        )

        raw = self._ask_ollama(merge_prompt, timeout=120)

        # Parse JSON from Ollama response
        try:
            m = re.search(r'\{.*\}', raw or "", re.DOTALL)
            if m:
                data = json.loads(m.group(0))
                tasks = [
                    Task(
                        id=t.get("id", i + 1),
                        description=t.get("description", ""),
                        depends_on=t.get("depends_on", []),
                    )
                    for i, t in enumerate(data.get("tasks", []))
                ]
                return ProjectPlan(
                    intent=intent,
                    stack=data.get("stack", []),
                    files=data.get("files", []),
                    tasks=tasks,
                    pitfalls=data.get("pitfalls", []),
                    claude_input=claude_response,
                    gpt_input=gpt_response,
                    created_at=datetime.now().isoformat(),
                )
        except Exception as exc:
            logger.warning("[Planner] Failed to parse merged plan: %s", exc)

        # Fallback: build a simple plan directly from Ollama
        return self._fallback_plan(intent, gpt_response or claude_response or "")

    def _fallback_plan(self, intent: str, hint: str) -> ProjectPlan:
        """Minimal plan when merge parsing fails."""
        tasks = [
            Task(id=1, description=f"Implement: {intent}", depends_on=[]),
            Task(id=2, description="Add error handling and tests", depends_on=[1]),
        ]
        return ProjectPlan(
            intent=intent,
            stack=["Python"],
            files=["main.py"],
            tasks=tasks,
            pitfalls=["Verify dependencies before running"],
            claude_input="",
            gpt_input=hint,
            created_at=datetime.now().isoformat(),
        )

    def execute_plan(
        self,
        plan: ProjectPlan,
        on_progress: Optional[Callable[[int, str], None]] = None,
    ) -> ExecutionResult:
        """Phase 2: run tasks in dependency order via Forge."""
        log = []
        completed = 0
        failed = 0
        status = _plan_status.setdefault(plan.id, {})
        status["status"] = "executing"

        def notify(task_id: int, msg: str):
            log.append(f"Task {task_id}: {msg}")
            status["log"] = log.copy()
            status["current_task"] = task_id
            if on_progress:
                try:
                    on_progress(task_id, msg)
                except Exception:
                    pass

        completed_ids: set[int] = set()

        for task in plan.tasks:
            # Wait for dependencies
            for dep in task.depends_on:
                if dep not in completed_ids:
                    notify(task.id, f"Waiting for task {dep}...")

            task.status = "running"
            task.attempts = 0
            notify(task.id, f"Starting: {task.description}")

            MAX_ATTEMPTS = 3
            result_code = None

            while task.attempts < MAX_ATTEMPTS:
                task.attempts += 1
                try:
                    resp = httpx.post(
                        f"{BACKEND_URL}/api/forge/request",
                        json={"prompt": task.description},
                        timeout=180,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if data.get("status") == "complete":
                            result_code = data.get("code", "")
                            break
                except Exception as exc:
                    logger.warning("[Planner] Forge request failed: %s", exc)

                if task.attempts >= MAX_ATTEMPTS:
                    notify(task.id, "Forge stuck — consulting ChatGPT...")
                    try:
                        fix = self.handle_stuck(task, task.attempts, "Forge failed to complete task")
                        result_code = fix
                        break
                    except Exception as exc:
                        logger.error("[Planner] Stuck handler failed: %s", exc)

            if result_code:
                task.status = "complete"
                task.result = result_code
                completed_ids.add(task.id)
                completed += 1
                notify(task.id, "Complete")
            else:
                task.status = "failed"
                failed += 1
                notify(task.id, "Failed after all attempts")

        status["status"] = "complete"
        return ExecutionResult(
            success=failed == 0,
            completed_tasks=completed,
            failed_tasks=failed,
            log=log,
        )

    def handle_stuck(self, task: "Task", attempts: int, last_error: str) -> str:
        """Phase 3: escalate stuck task."""
        use_codex = self.consultant.should_use_codex(task.description, last_error)
        if use_codex:
            result = self.consultant.consult_for_code(
                problem=task.description,
                code="",
                error=last_error,
            )
            return result.answer
        elif self.consultant.alternative_approach:
            alt = self.consultant.alternative_approach
            result = self.consultant.consult_for_code(
                problem=alt,
                code="",
                error=last_error,
            )
            return result.answer
        raise RuntimeError(f"All escalation paths exhausted for task {task.id}")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_planner: Optional[ProjectPlanner] = None


def get_project_planner() -> ProjectPlanner:
    global _planner
    if _planner is None:
        _planner = ProjectPlanner()
    return _planner
