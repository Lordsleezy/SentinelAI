"""Central registry for supervised Sentinel tools."""

from typing import Dict

from execution_tools import DryRunTerminalTool, GitStatusTool, ListFilesTool, ReadTextFileTool


class ToolRegistry:
    def __init__(self):
        self.tools = {
            "list_files": ListFilesTool(),
            "read_text_file": ReadTextFileTool(),
            "git_status": GitStatusTool(),
            "terminal_dry_run": DryRunTerminalTool(),
        }

    def list_tools(self) -> Dict:
        return {
            name: {
                "name": tool.name,
                "requires_approval": tool.requires_approval,
            }
            for name, tool in self.tools.items()
        }

    def run_tool(self, name: str, **kwargs):
        if name not in self.tools:
            raise ValueError(f"Unknown tool: {name}")
        return self.tools[name].run(**kwargs)


_registry = None


def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
