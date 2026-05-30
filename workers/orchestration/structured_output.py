"""
Structured Output Enforcement — Forces JSON output with schema validation
"""
import json
import logging
import re
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

CAPABILITY_DESCRIPTION = "Enforces JSON schema on LLM outputs to reduce hallucination"

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


# Pre-built JSON schemas for common tasks
SCHEMAS = {
    "task_decomposition": {
        "type": "object",
        "properties": {
            "complexity": {"type": "string", "enum": ["SIMPLE", "COMPLEX"]},
            "subtasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string"},
                        "type": {"type": "string"}
                    }
                }
            }
        },
        "required": ["complexity", "subtasks"]
    },

    "code_task": {
        "type": "object",
        "properties": {
            "code": {"type": "string"},
            "explanation": {"type": "string"},
            "confidence": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]}
        },
        "required": ["code"]
    },

    "verification": {
        "type": "object",
        "properties": {
            "passed": {"type": "boolean"},
            "reason": {"type": "string"},
            "confidence": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]}
        },
        "required": ["passed"]
    },

    "capability_check": {
        "type": "object",
        "properties": {
            "available": {"type": "boolean"},
            "reason": {"type": "string"},
            "alternatives": {
                "type": "array",
                "items": {"type": "string"}
            }
        },
        "required": ["available"]
    }
}


class StructuredOutput:
    """Enforces structured JSON output from LLMs"""

    def __init__(self):
        self.ollama_host = os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434')
        self.ollama_model = os.getenv('OLLAMA_MODEL', 'qwen2.5-coder:14b')

    def enforce_json(
        self,
        prompt: str,
        schema: Dict[str, Any],
        model: str = None,
        max_retries: int = 3
    ) -> Optional[Dict[str, Any]]:
        """Call LLM with forced JSON output and validation"""

        if not HTTPX_AVAILABLE:
            logger.warning("httpx not available - returning empty dict")
            return {}

        if model is None:
            model = self.ollama_model

        # Build prompt with schema requirement
        schema_str = json.dumps(schema, indent=2)
        full_prompt = f"""{prompt}

You MUST respond with ONLY valid JSON matching this schema:
{schema_str}

Respond with nothing but the JSON object."""

        for attempt in range(max_retries):
            try:
                with httpx.Client() as client:
                    response = client.post(
                        f"{self.ollama_host}/api/generate",
                        json={
                            "model": model,
                            "prompt": full_prompt,
                            "stream": False
                        },
                        timeout=30.0
                    )

                    if response.status_code == 200:
                        data = response.json()
                        result_text = data.get('response', '').strip()

                        # Try to extract JSON
                        parsed = self._extract_json(result_text)

                        if parsed:
                            # Validate against schema
                            if self._validate_schema(parsed, schema):
                                return parsed
                            else:
                                logger.warning(f"Attempt {attempt + 1}: JSON didn't match schema")
                                continue

            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed: {e}")

        logger.error(f"Failed to get valid JSON after {max_retries} attempts")
        return None

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from text"""
        # Try direct parsing first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON object from text
        # Look for { ... }
        json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # Try to clean up and parse
        # Remove markdown code blocks
        cleaned = re.sub(r'```(?:json)?\s*\n?', '', text)
        cleaned = cleaned.strip()

        if cleaned.startswith('{') and cleaned.endswith('}'):
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass

        return None

    def _validate_schema(self, data: Dict[str, Any], schema: Dict[str, Any]) -> bool:
        """Simple schema validation"""
        required = schema.get('required', [])

        for field in required:
            if field not in data:
                logger.warning(f"Missing required field: {field}")
                return False

        return True

    def fill_defaults(self, data: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
        """Fill in missing fields with None"""
        properties = schema.get('properties', {})

        for prop, prop_schema in properties.items():
            if prop not in data:
                # Infer default value
                if prop_schema.get('type') == 'boolean':
                    data[prop] = False
                elif prop_schema.get('type') == 'array':
                    data[prop] = []
                elif prop_schema.get('type') == 'string':
                    data[prop] = ""
                else:
                    data[prop] = None

        return data


import os


# Pre-built templates
def get_code_generation_prompt(task: str, context: str = "") -> str:
    """Build prompt for code generation with schema"""
    return f"""Task: {task}

{f"Context: {context}" if context else ""}

Generate Python code that solves this task.
Respond with valid JSON:
{{
  "code": "... python code ...",
  "explanation": "... brief explanation ...",
  "confidence": "HIGH|MEDIUM|LOW"
}}"""


def get_verification_prompt(task: str, result: str) -> str:
    """Build prompt for verification with schema"""
    return f"""Task: {task}

Result: {result}

Did this result successfully complete the task? Respond with:
{{
  "passed": true/false,
  "reason": "explanation if failed",
  "confidence": "HIGH|MEDIUM|LOW"
}}"""


_structured = None


def get_structured_output() -> StructuredOutput:
    global _structured
    if _structured is None:
        _structured = StructuredOutput()
    return _structured
