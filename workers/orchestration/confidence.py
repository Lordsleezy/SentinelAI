"""
Confidence Scoring and Auto-Escalation — Wraps Ollama with Claude API fallback
"""
import os
import re
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

CAPABILITY_DESCRIPTION = "Wraps Ollama calls with confidence scoring and auto-escalation to Claude API"

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


class ConfidenceWrapper:
    """Wraps AI calls with confidence scoring and auto-escalation"""

    def __init__(self):
        self.ollama_host = os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434')
        self.ollama_model = os.getenv('OLLAMA_MODEL', 'qwen2.5-coder:14b')
        self.anthropic_api_key = os.getenv('ANTHROPIC_API_KEY')

    def ollama_with_confidence(self, prompt: str, model: str = None) -> Dict[str, Any]:
        """Call Ollama with confidence scoring"""
        if not HTTPX_AVAILABLE:
            return {
                "response": None,
                "confidence": "LOW",
                "model": "ollama",
                "escalated": False
            }

        if model is None:
            model = self.ollama_model

        # Append confidence request
        full_prompt = f"""{prompt}

After your response, on a new line write exactly:
CONFIDENCE: HIGH
or
CONFIDENCE: MEDIUM
or
CONFIDENCE: LOW

HIGH = I am certain this is correct
MEDIUM = I think this is correct but not sure
LOW = I am guessing or this is beyond my ability"""

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
                    full_response = data.get('response', '').strip()

                    # Extract confidence level
                    confidence = "MEDIUM"  # Default
                    if 'CONFIDENCE: HIGH' in full_response:
                        confidence = "HIGH"
                    elif 'CONFIDENCE: LOW' in full_response:
                        confidence = "LOW"
                    elif 'CONFIDENCE: MEDIUM' in full_response:
                        confidence = "MEDIUM"

                    # Strip confidence line from response
                    clean_response = re.sub(r'\n*CONFIDENCE:\s*(HIGH|MEDIUM|LOW)\s*$', '', full_response, flags=re.IGNORECASE)

                    return {
                        "response": clean_response.strip(),
                        "confidence": confidence,
                        "model": "ollama",
                        "escalated": False
                    }

        except Exception as e:
            logger.error(f"Ollama call failed: {e}")

        return {
            "response": None,
            "confidence": "LOW",
            "model": "ollama",
            "escalated": False
        }

    def call_claude_api(self, prompt: str, context: str = "") -> Dict[str, Any]:
        """Escalate to Claude API"""
        if not self.anthropic_api_key:
            logger.warning("ANTHROPIC_API_KEY not set - cannot escalate")
            return {
                "response": None,
                "confidence": "LOW",
                "model": "claude-api",
                "escalated": False,
                "error": "API key not configured"
            }

        if not HTTPX_AVAILABLE:
            return {
                "response": None,
                "confidence": "LOW",
                "model": "claude-api",
                "escalated": False,
                "error": "httpx not available"
            }

        full_prompt = f"{context}\n\n{prompt}" if context else prompt

        try:
            with httpx.Client() as client:
                response = client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self.anthropic_api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json"
                    },
                    json={
                        "model": "claude-haiku-4-5-20251001",
                        "max_tokens": 4096,
                        "messages": [
                            {
                                "role": "user",
                                "content": full_prompt
                            }
                        ]
                    },
                    timeout=60.0
                )

                if response.status_code == 200:
                    data = response.json()
                    content = data.get('content', [])

                    if content and len(content) > 0:
                        text = content[0].get('text', '')

                        return {
                            "response": text,
                            "confidence": "HIGH",
                            "model": "claude-haiku",
                            "escalated": True
                        }

        except Exception as e:
            logger.error(f"Claude API call failed: {e}")

        return {
            "response": None,
            "confidence": "LOW",
            "model": "claude-api",
            "escalated": False,
            "error": "API call failed"
        }

    def call_with_fallback(self, prompt: str, context: str = "") -> Dict[str, Any]:
        """Call with automatic escalation on low confidence"""
        # Try Ollama first
        result = self.ollama_with_confidence(prompt)

        # HIGH confidence - return directly
        if result["confidence"] == "HIGH":
            return result

        # MEDIUM confidence - for now return (self-verification would go here in Track 19)
        if result["confidence"] == "MEDIUM":
            return result

        # LOW confidence - escalate to Claude
        if result["confidence"] == "LOW":
            logger.info("Low confidence detected - escalating to Claude API")
            claude_result = self.call_claude_api(prompt, context)

            # If Claude succeeds, return that
            if claude_result.get("response"):
                return claude_result

            # If Claude fails too, return the Ollama result with warning
            result["escalation_attempted"] = True
            result["escalation_failed"] = True
            return result

        return result


# Global instance
_confidence_wrapper = None


def get_confidence_wrapper() -> ConfidenceWrapper:
    """Get or create global confidence wrapper"""
    global _confidence_wrapper
    if _confidence_wrapper is None:
        _confidence_wrapper = ConfidenceWrapper()
    return _confidence_wrapper
