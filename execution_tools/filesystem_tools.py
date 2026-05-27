"""Filesystem tools with read-only defaults."""

from pathlib import Path

from tools import SentinelTool, ToolResult


class ListFilesTool(SentinelTool):
    name = "list_files"
    requires_approval = False

    def run(self, root: str, limit: int = 200) -> ToolResult:
        base = Path(root).resolve()
        files = []
        for path in base.rglob("*"):
            if len(files) >= limit:
                break
            if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts:
                files.append(str(path.relative_to(base)))
        return ToolResult(True, "\n".join(files), {"root": str(base), "count": len(files)})


class ReadTextFileTool(SentinelTool):
    name = "read_text_file"
    requires_approval = False

    def run(self, path: str, max_chars: int = 12000) -> ToolResult:
        target = Path(path).resolve()
        content = target.read_text(encoding="utf-8", errors="ignore")[:max_chars]
        return ToolResult(True, content, {"path": str(target), "chars": len(content)})
