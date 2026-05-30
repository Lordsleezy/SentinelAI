"""
Task Decomposition Pipeline — Breaks complex requests into executable subtasks
"""
import os
import re
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

CAPABILITY_DESCRIPTION = "Breaks complex user requests into small executable subtasks"

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    logger.warning("httpx not available - task decomposition disabled")


class TaskDecomposer:
    """Decomposes complex tasks into executable subtasks with routing"""

    def __init__(self):
        self.ollama_host = os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434')
        self.ollama_model = os.getenv('OLLAMA_MODEL', 'qwen2.5-coder:14b')

        # Route map for task types
        self.route_map = {
            "CODE": "forge",
            "FILE": "forge",
            "WEB": "openclaw.web",
            "MEMORY": "memory",
            "HOME": "home_assistant",
            "CALENDAR": "openclaw.calendar",
            "MUSIC": "entertainment.spotify",
            "FINANCE": "finance.firefly",
            "CAMERA": "home.camera_worker",
            "EARN": "earn",
            "MARKET": "market",
            "GENERAL": "ollama_general"
        }

        self.valid_types = list(self.route_map.keys())

    def classify_complexity(self, user_request: str) -> str:
        """Classify request as SIMPLE or COMPLEX"""
        if not HTTPX_AVAILABLE:
            logger.warning("httpx not available - defaulting to SIMPLE")
            return "SIMPLE"

        prompt = f"""Classify this request as SIMPLE or COMPLEX.
SIMPLE = completable in one step by one worker.
COMPLEX = requires multiple steps or multiple workers.

Request: {user_request}

Reply with ONLY the word SIMPLE or COMPLEX."""

        try:
            with httpx.Client() as client:
                response = client.post(
                    f"{self.ollama_host}/api/generate",
                    json={
                        "model": self.ollama_model,
                        "prompt": prompt,
                        "stream": False
                    },
                    timeout=10.0
                )

                if response.status_code == 200:
                    data = response.json()
                    result = data.get('response', '').strip().upper()

                    if 'COMPLEX' in result:
                        return "COMPLEX"
                    else:
                        return "SIMPLE"

        except Exception as e:
            logger.error(f"Complexity classification failed: {e}")

        return "SIMPLE"  # Fail-safe

    def decompose(self, user_request: str) -> List[str]:
        """Decompose request into numbered subtasks"""
        if not HTTPX_AVAILABLE:
            logger.warning("httpx not available - returning single task")
            return [user_request]

        prompt = f"""Break this request into a numbered list of small independent subtasks.
Each subtask must:
- Be completable in one step
- Be specific and unambiguous
- Produce a clear measurable output

Request: {user_request}

Reply in EXACTLY this format, nothing else:
SUBTASK_1: [description]
SUBTASK_2: [description]
SUBTASK_3: [description]

Maximum 8 subtasks. Be as specific as possible."""

        try:
            with httpx.Client() as client:
                response = client.post(
                    f"{self.ollama_host}/api/generate",
                    json={
                        "model": self.ollama_model,
                        "prompt": prompt,
                        "stream": False
                    },
                    timeout=30.0
                )

                if response.status_code == 200:
                    data = response.json()
                    result = data.get('response', '').strip()

                    # Parse SUBTASK_N: format
                    subtasks = []
                    for line in result.split('\n'):
                        match = re.match(r'SUBTASK_\d+:\s*(.+)', line.strip())
                        if match:
                            subtasks.append(match.group(1).strip())

                    if subtasks:
                        # Truncate to max 8
                        return subtasks[:8]

        except Exception as e:
            logger.error(f"Task decomposition failed: {e}")

        # Fail-safe: return original request as single task
        return [user_request]

    def classify_type(self, subtask: str) -> str:
        """Classify subtask into a task type category"""
        if not HTTPX_AVAILABLE:
            return "GENERAL"

        valid_types_str = ", ".join(self.valid_types)

        prompt = f"""Classify this task into exactly ONE category from this list:
{valid_types_str}

Task: {subtask}

Reply with ONLY the category name, nothing else."""

        try:
            with httpx.Client() as client:
                response = client.post(
                    f"{self.ollama_host}/api/generate",
                    json={
                        "model": self.ollama_model,
                        "prompt": prompt,
                        "stream": False
                    },
                    timeout=10.0
                )

                if response.status_code == 200:
                    data = response.json()
                    result = data.get('response', '').strip().upper()

                    # Extract the type
                    for valid_type in self.valid_types:
                        if valid_type in result:
                            return valid_type

        except Exception as e:
            logger.error(f"Type classification failed: {e}")

        return "GENERAL"  # Fail-safe

    def route(self, task_type: str) -> str:
        """Route task type to worker"""
        return self.route_map.get(task_type, "ollama_general")

    def generate_plan(self, user_request: str) -> Dict[str, Any]:
        """Generate complete execution plan from user request"""
        # Step 1: Classify complexity
        complexity = self.classify_complexity(user_request)

        # Simple tasks - single subtask
        if complexity == "SIMPLE":
            task_type = self.classify_type(user_request)
            worker = self.route(task_type)

            return {
                "complexity": "simple",
                "original_request": user_request,
                "subtasks": [
                    {
                        "index": 1,
                        "task": user_request,
                        "type": task_type,
                        "worker": worker,
                        "status": "pending",
                        "result": None
                    }
                ]
            }

        # Complex tasks - decompose and route each
        else:
            subtask_strings = self.decompose(user_request)

            subtasks = []
            for i, subtask_str in enumerate(subtask_strings):
                task_type = self.classify_type(subtask_str)
                worker = self.route(task_type)

                subtasks.append({
                    "index": i + 1,
                    "task": subtask_str,
                    "type": task_type,
                    "worker": worker,
                    "status": "pending",
                    "result": None
                })

            return {
                "complexity": "complex",
                "original_request": user_request,
                "subtasks": subtasks
            }


# Global instance
_decomposer = None


def get_decomposer() -> TaskDecomposer:
    """Get or create global decomposer instance"""
    global _decomposer
    if _decomposer is None:
        _decomposer = TaskDecomposer()
    return _decomposer
