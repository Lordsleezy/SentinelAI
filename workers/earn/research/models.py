"""Earn Research Mode data models."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class FindingStatus(str, Enum):
    IDEA = "Idea"
    INVESTIGATING = "Investigating"
    NEEDS_VALIDATION = "Needs Validation"
    VALIDATED = "Validated"
    REJECTED = "Rejected"
    READY_FOR_REVIEW = "Ready for Human Review"


class WorkflowStage(str, Enum):
    IDEA = "idea"
    RESEARCH = "research"
    EVIDENCE = "evidence"
    VALIDATION = "validation"
    HUMAN_REVIEW = "human_review"


@dataclass
class PotentialFinding:
    id: str
    title: str
    target: str
    category: str
    evidence: str
    confidence: float
    status: str = FindingStatus.IDEA.value
    workflow_stage: str = WorkflowStage.IDEA.value
    suggested_research: List[str] = field(default_factory=list)
    detected_technologies: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchPlanItem:
    target: str
    detected: List[str]
    suggested_research: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HostTechnology:
    url: str
    framework: List[str] = field(default_factory=list)
    cms: List[str] = field(default_factory=list)
    cloud: List[str] = field(default_factory=list)
    auth: List[str] = field(default_factory=list)
    api_tech: List[str] = field(default_factory=list)
    raw_tech: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceItem:
    id: str
    kind: str  # request | response | screenshot | note | log
    path: str
    summary: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SubmissionPlaceholders:
    """Phase 10 — not implemented; placeholders only."""
    submission_draft: Optional[str] = None
    impact_analysis: Optional[str] = None
    reproduction_steps: Optional[str] = None
    note: str = "Automatic submission not implemented — human review required."

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchSession:
    id: str
    program_handle: str
    program_title: str
    status: str = "running"
    current_stage: str = "Starting"
    progress_percent: int = 0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    scope_summary: str = ""
    in_scope_assets: List[str] = field(default_factory=list)
    targets_probed: List[str] = field(default_factory=list)
    technologies: List[Dict[str, Any]] = field(default_factory=list)
    research_plan: List[Dict[str, Any]] = field(default_factory=list)
    potential_findings: List[Dict[str, Any]] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    recon_outputs: Dict[str, Any] = field(default_factory=dict)
    submission_placeholders: Dict[str, Any] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)
    error: Optional[str] = None

    @staticmethod
    def new_id() -> str:
        return f"res_{uuid.uuid4().hex[:12]}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
