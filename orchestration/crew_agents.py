"""
CrewAI worker-agent layer for SentinelAI.

The runtime keeps a small local fallback implementation so tests and offline
development work even before CrewAI is installed. When CrewAI is present, each
Sentinel worker can expose a CrewAI Agent object through `crew_agent`.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .models import AgentRole
from . import persistence


try:
    from crewai import Agent as CrewAIAgent  # type: ignore
except Exception:  # pragma: no cover - exercised when dependency unavailable
    CrewAIAgent = None


@dataclass
class AgentResult:
    success: bool
    agent_name: str
    output: Dict[str, Any]
    error: str = ""


class SentinelCrewWorker:
    """Small, stateful wrapper around a specialized Sentinel worker role."""

    def __init__(self, role: AgentRole, goal: str, backstory: str):
        self.role = role
        self.name = role.value
        self.goal = goal
        self.backstory = backstory
        self.crew_agent = self._create_crewai_agent()

    def _create_crewai_agent(self) -> Optional[Any]:
        if CrewAIAgent is None:
            return None
        return CrewAIAgent(
            role=self.name,
            goal=self.goal,
            backstory=self.backstory,
            allow_delegation=False,
            verbose=False,
        )

    def execute(self, task: Dict[str, Any]) -> AgentResult:
        """Execute a delegated task and persist compact agent memory."""
        workflow_id = task.get("workflow_id")
        objective = task.get("goal", "")
        persistence.log_execution(
            "agent_task_started",
            f"{self.name}: {objective}",
            workflow_id=workflow_id,
            agent_name=self.name,
        )
        memory = persistence.get_agent_memory(self.name, "execution_summary")
        run_count = int(memory.get("run_count", 0)) + 1
        memory.update(
            {
                "run_count": run_count,
                "last_goal": objective,
                "last_workflow_id": workflow_id,
            }
        )
        persistence.set_agent_memory(self.name, "execution_summary", memory)

        output = {
            "agent": self.name,
            "mode": "crewai" if self.crew_agent is not None else "sentinel_fallback",
            "summary": self._summarize_task(objective),
            "next_steps": self._next_steps(task),
        }
        persistence.log_execution(
            "agent_task_completed",
            output["summary"],
            workflow_id=workflow_id,
            agent_name=self.name,
        )
        return AgentResult(success=True, agent_name=self.name, output=output)

    def _summarize_task(self, objective: str) -> str:
        if self.role == AgentRole.RESEARCH:
            return f"Research scoped for: {objective}"
        if self.role == AgentRole.CODING:
            return f"Coding task prepared for: {objective}"
        if self.role == AgentRole.DEBUGGING:
            return f"Debugging path prepared for: {objective}"
        if self.role == AgentRole.UI:
            return f"UI implementation path prepared for: {objective}"
        if self.role == AgentRole.MONITORING:
            return f"Monitoring review prepared for: {objective}"
        if self.role == AgentRole.DEPLOYMENT:
            return f"Deployment plan prepared for: {objective}"
        if self.role == AgentRole.REVENUE_DISCOVERY:
            return f"Revenue discovery scan prepared for: {objective}"
        return f"Task prepared for: {objective}"

    def _next_steps(self, task: Dict[str, Any]) -> list:
        return [
            "confirm safety constraints",
            "execute through Sentinel queue/workflow controls",
            "persist result and checkpoint",
        ]


class WorkerAgentRegistry:
    """Registry of Sentinel CrewAI-compatible worker agents."""

    def __init__(self):
        self.agents = {
            AgentRole.RESEARCH.value: SentinelCrewWorker(
                AgentRole.RESEARCH,
                "Gather reliable context and constraints before execution.",
                "A careful research worker that summarizes inputs without leaking secrets.",
            ),
            AgentRole.CODING.value: SentinelCrewWorker(
                AgentRole.CODING,
                "Implement scoped code changes safely.",
                "A disciplined coding worker that prefers incremental edits and tests.",
            ),
            AgentRole.DEBUGGING.value: SentinelCrewWorker(
                AgentRole.DEBUGGING,
                "Diagnose failures and propose recoverable fixes.",
                "A debugging worker focused on logs, reproduction, and rollback safety.",
            ),
            AgentRole.UI.value: SentinelCrewWorker(
                AgentRole.UI,
                "Handle user interface implementation tasks.",
                "A UI worker that preserves existing design systems and accessibility.",
            ),
            AgentRole.MONITORING.value: SentinelCrewWorker(
                AgentRole.MONITORING,
                "Inspect health, telemetry, queues, and watchdog state.",
                "A monitoring worker focused on observability and operational drift.",
            ),
            AgentRole.DEPLOYMENT.value: SentinelCrewWorker(
                AgentRole.DEPLOYMENT,
                "Prepare deployment and release tasks.",
                "A deployment worker that respects dry-run and approval gates.",
            ),
            AgentRole.REVENUE_DISCOVERY.value: SentinelCrewWorker(
                AgentRole.REVENUE_DISCOVERY,
                "Find and score revenue opportunities.",
                "A revenue worker that coordinates with scanner and learning memory.",
            ),
        }

    def choose_agent(self, workflow_type: str, goal: str) -> SentinelCrewWorker:
        text = f"{workflow_type} {goal}".lower()
        if any(word in text for word in ("debug", "fix failure", "traceback", "error")):
            return self.agents[AgentRole.DEBUGGING.value]
        if any(word in text for word in ("ui", "frontend", "css", "electron")):
            return self.agents[AgentRole.UI.value]
        if any(word in text for word in ("deploy", "release", "ship", "railway", "render")):
            return self.agents[AgentRole.DEPLOYMENT.value]
        if any(word in text for word in ("monitor", "health", "watchdog", "queue")):
            return self.agents[AgentRole.MONITORING.value]
        if any(word in text for word in ("revenue", "bounty", "scan", "issuehunt", "algora")):
            return self.agents[AgentRole.REVENUE_DISCOVERY.value]
        if any(word in text for word in ("research", "investigate", "read", "analyze")):
            return self.agents[AgentRole.RESEARCH.value]
        return self.agents[AgentRole.CODING.value]

    def list_agents(self) -> Dict[str, Dict[str, Any]]:
        return {
            name: {
                "name": agent.name,
                "goal": agent.goal,
                "crewai_available": agent.crew_agent is not None,
            }
            for name, agent in self.agents.items()
        }
