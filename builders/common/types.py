"""Shared types for all Sentinel builders."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class VerificationResult:
    verified: bool
    message: str = ""
    attempted_repair: bool = False


@dataclass
class BuildResult:
    success: bool
    builder: str
    project_type: str
    output_dir: str = ""
    entry_point: str = ""
    launch_command: str = ""
    files: List[str] = field(default_factory=list)
    build_logs: str = ""
    verification: Optional[VerificationResult] = None
    error: Optional[str] = None
    artifact_type: str = "app"

    @property
    def verified(self) -> bool:
        return bool(self.verification and self.verification.verified)
