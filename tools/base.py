"""Base classes for supervised tools."""

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class ToolResult:
    success: bool
    output: str
    metadata: Dict[str, Any]
    error: str = ""


class SentinelTool:
    name = "base"
    requires_approval = True

    def run(self, **kwargs) -> ToolResult:
        raise NotImplementedError
