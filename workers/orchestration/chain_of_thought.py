"""
Chain of Thought Reasoning — Prepends thinking scaffolds for improved task reasoning
"""
import os
import re
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

CAPABILITY_DESCRIPTION = "Applies chain-of-thought reasoning for improved code task quality"


class ChainOfThought:
    """Generates COT reasoning scaffolds for different task types"""

    COT_TEMPLATES = {
        "CODE": """Let me think about this step by step:
1. What is the exact requirement?
2. What existing patterns in the codebase apply?
3. What are critical edge cases?
4. How should this integrate with existing code?
5. What tests would verify success?

Now I'll implement this:""",

        "FILE": """Breaking down this file task:
1. What files/directories are involved?
2. What is the current structure?
3. What exactly needs to change?
4. How do changes affect other components?
5. Are there file-level dependencies?

Implementation:""",

        "WEB": """For this web request:
1. What URL/endpoint is needed?
2. What are the parameters and headers?
3. How should the response be formatted?
4. What error cases might occur?
5. How should caching or rate limits work?

Proceeding:""",

        "CODE_REVIEW": """Analyzing this code:
1. What is the code trying to do?
2. Are there logic errors?
3. Are there performance issues?
4. Are there security concerns?
5. What could be improved?

Analysis:""",

        "GENERAL": """Let me approach this systematically:
1. What is the core requirement?
2. What information is available?
3. What are the main steps?
4. What might go wrong?
5. How can I verify the result?

Answer:"""
    }

    def __init__(self):
        self.codebase_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    def extract_code_context(self, task: str, max_length: int = 1500) -> str:
        """Extract relevant code snippets from codebase"""
        context_pieces = []

        # Look for file/function/class names in task
        file_refs = re.findall(r'(?:file|path|module)[\s:]*["\']?([a-zA-Z0-9_/.-]+\.py)["\']?', task, re.IGNORECASE)
        func_refs = re.findall(r'(?:function|def|method|class)[\s:]*["\']?([a-zA-Z_][a-zA-Z0-9_]*)["\']?', task, re.IGNORECASE)

        # Search for referenced files
        for file_ref in file_refs[:2]:
            try:
                file_path = os.path.join(self.codebase_root, file_ref)
                if os.path.isfile(file_path):
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read(800)
                        context_pieces.append(f"File: {file_ref}\n{content}")
                        if len('\n'.join(context_pieces)) > max_length:
                            break
            except Exception as e:
                logger.debug(f"Could not read {file_ref}: {e}")

        # Search workers directory for referenced functions
        if not context_pieces:
            try:
                workers_path = os.path.join(self.codebase_root, 'workers')
                if os.path.isdir(workers_path):
                    for root, dirs, files in os.walk(workers_path):
                        dirs[:] = [d for d in dirs if d not in ['__pycache__', '.git']]
                        for file in [f for f in files if f.endswith('.py')][:3]:
                            try:
                                file_path = os.path.join(root, file)
                                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                    content = f.read(600)
                                    context_pieces.append(f"File: {file}\n{content}")
                                    if len('\n'.join(context_pieces)) > max_length:
                                        break
                            except:
                                pass
                        if len('\n'.join(context_pieces)) > max_length:
                            break
            except Exception as e:
                logger.debug(f"Could not search workers: {e}")

        result = '\n'.join(context_pieces)
        return result[:max_length] if result else ""

    def apply_cot_prefix(self, task: str, task_type: str, codebase_context: str = "") -> str:
        """Prepend COT scaffold to task"""
        template = self.COT_TEMPLATES.get(task_type, self.COT_TEMPLATES["GENERAL"])

        result = f"{template}\n\n"

        if codebase_context:
            result += f"Relevant code context:\n{codebase_context}\n\n"

        result += f"Task: {task}"

        return result

    def extract_type_from_task(self, task: str) -> str:
        """Guess task type for appropriate COT template"""
        task_lower = task.lower()

        if any(w in task_lower for w in ['code', 'function', 'class', 'implement', 'write']):
            return "CODE"
        elif any(w in task_lower for w in ['file', 'directory', 'rename', 'move', 'create file']):
            return "FILE"
        elif any(w in task_lower for w in ['http', 'request', 'api', 'endpoint', 'url']):
            return "WEB"
        elif any(w in task_lower for w in ['review', 'check', 'audit', 'analyze']):
            return "CODE_REVIEW"

        return "GENERAL"


_cot = None


def get_cot() -> ChainOfThought:
    global _cot
    if _cot is None:
        _cot = ChainOfThought()
    return _cot
