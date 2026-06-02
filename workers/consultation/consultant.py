"""Consultation worker.

Hierarchy:
  1. Ollama (local, always first)
  2. Codex CLI (coding, after Ollama fails 3x + GPT approval)
  3. ChatGPT browser  (guidance / architecture)
  4. Claude.ai browser (fallback if ChatGPT unavailable)
  5. Ollama fallback  (if all browser automation fails)
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

SENTINELWEB_URL = os.getenv("SENTINELWEB_URL", "http://localhost:8766")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:14b")

# Identity prefix sent at the start of every new consultation
SENTINEL_IDENTITY_PREFIX = """Hi, I'm Sentinel — {user_name}'s personal AI operating system, \
built by Sentinel Prime Inc. I'm consulting you on {user_name}'s behalf. \
Please address me as Sentinel in this conversation.

{user_name}'s current context:
{memory_context}

My question/task:
{prompt}"""

# Memory request sent at the end of every consultation
SENTINEL_MEMORY_REQUEST = """Please save this to your memory:
- Sentinel ({user_name}'s AI assistant) consulted you about: {topic}
- Date: {date}
- Key decisions or recommendations: {summary}
- This is part of an ongoing project: {project_context}"""


def _build_identity_prompt(prompt: str, user_name: str = "Paul",
                            memory_context: str = "") -> str:
    return SENTINEL_IDENTITY_PREFIX.format(
        user_name=user_name,
        memory_context=memory_context or "No specific context loaded.",
        prompt=prompt,
    )


def _summarize_response(response: str) -> str:
    """Quick 2-3 sentence summary using simple truncation (no LLM cost)."""
    sentences = [s.strip() for s in response.replace('\n', ' ').split('.') if s.strip()]
    summary = '. '.join(sentences[:3])
    return summary[:400] if len(summary) > 400 else summary


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ConsultationResult:
    source: str          # "chatgpt" | "claude" | "codex" | "ollama_fallback"
    answer: str
    success: bool
    alternative_approach: Optional[str] = None


# ---------------------------------------------------------------------------
# Consultant
# ---------------------------------------------------------------------------

class Consultant:
    def __init__(self):
        self.sentinelweb_url = SENTINELWEB_URL
        self.alternative_approach: Optional[str] = None
        self.codex_available = self._check_codex()

    # ------------------------------------------------------------------ codex

    def _check_codex(self) -> bool:
        """True if the codex CLI is installed."""
        try:
            result = subprocess.run(
                ["codex", "--version"],
                capture_output=True, text=True, timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def ask_codex(self, prompt: str) -> Optional[str]:
        """Run codex CLI and return stdout. Returns None on any failure."""
        if not self.codex_available:
            return None
        try:
            result = subprocess.run(
                ["codex", prompt],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logger.warning("[Consultant] codex failed: %s", exc)
        return None

    # ---------------------------------------------------------------- SentinelWeb

    def _sentinelweb_available(self) -> bool:
        try:
            resp = httpx.get(f"{self.sentinelweb_url}/status", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def _sentinelweb_ask(self, site: str, prompt: str, timeout: int = 60) -> Optional[str]:
        """
        Ask a question via SentinelWeb browser automation.
        site: 'chatgpt' | 'claude'
        """
        if not self._sentinelweb_available():
            return None
        try:
            resp = httpx.post(
                f"{self.sentinelweb_url}/ask",
                json={"site": site, "prompt": prompt, "timeout": timeout},
                timeout=timeout + 10,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("response") or data.get("answer")
        except Exception as exc:
            logger.debug("[Consultant] SentinelWeb %s error: %s", site, exc)
        return None

    def ask_chatgpt(self, prompt: str, use_identity: bool = True,
                    user_name: str = "Paul", memory_context: str = "") -> Optional[str]:
        """Ask ChatGPT with Sentinel identity prefix."""
        if use_identity:
            full_prompt = _build_identity_prompt(prompt, user_name, memory_context)
        else:
            full_prompt = prompt
        return self._sentinelweb_ask("chatgpt", full_prompt, timeout=60)

    def ask_claude(self, prompt: str, use_identity: bool = True,
                   user_name: str = "Paul", memory_context: str = "") -> Optional[str]:
        """Ask Claude with Sentinel identity prefix."""
        if use_identity:
            full_prompt = _build_identity_prompt(prompt, user_name, memory_context)
        else:
            full_prompt = prompt
        return self._sentinelweb_ask("claude", full_prompt, timeout=60)

    # ---------------------------------------------------------------- Ollama

    def _ask_ollama(self, prompt: str, timeout: int = 60) -> Optional[str]:
        try:
            resp = httpx.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
                timeout=timeout,
            )
            if resp.status_code == 200:
                return resp.json().get("response", "").strip()
        except Exception as exc:
            logger.debug("[Consultant] Ollama error: %s", exc)
        return None

    # ---------------------------------------------------------------- Main API

    def _get_user_name(self) -> str:
        try:
            from workers.identity.identity_manager import get_identity_manager
            return get_identity_manager().get_user_name()
        except Exception:
            return "Paul"

    def consult_for_guidance(self, question: str, context: str = "") -> ConsultationResult:
        """
        Get architectural / strategic guidance.
        Tries ChatGPT, then Claude, then Ollama.
        Wraps with Sentinel identity prefix.
        """
        user_name = self._get_user_name()
        full_prompt = question
        if context:
            full_prompt = f"{question}\n\nContext:\n{context}"

        # Try ChatGPT first (with Sentinel identity)
        answer = self.ask_chatgpt(full_prompt, use_identity=True, user_name=user_name)
        if answer:
            return ConsultationResult(source="chatgpt", answer=answer, success=True)

        # Claude fallback
        answer = self.ask_claude(full_prompt, use_identity=True, user_name=user_name)
        if answer:
            return ConsultationResult(source="claude", answer=answer, success=True)

        # Ollama last resort (no identity prefix needed — local model)
        answer = self._ask_ollama(full_prompt, timeout=90)
        return ConsultationResult(
            source="ollama_fallback",
            answer=answer or "Unable to retrieve guidance at this time.",
            success=bool(answer),
        )

    def consult_for_code(self, problem: str, code: str, error: str) -> ConsultationResult:
        """
        Get a coding fix. Called after Ollama fails 3x AND GPT approves Codex.
        """
        prompt = (
            f"Fix this code problem:\n\nProblem: {problem}\n\n"
            f"Code:\n{code}\n\nError:\n{error}\n\n"
            "Provide only the corrected code without explanations."
        )

        # Try Codex first (best for code)
        answer = self.ask_codex(prompt)
        if answer:
            return ConsultationResult(source="codex", answer=answer, success=True)

        # Fall back to ChatGPT
        answer = self.ask_chatgpt(prompt)
        if answer:
            return ConsultationResult(source="chatgpt", answer=answer, success=True)

        # Claude fallback
        answer = self.ask_claude(prompt)
        if answer:
            return ConsultationResult(source="claude", answer=answer, success=True)

        # Ollama final fallback
        answer = self._ask_ollama(prompt)
        return ConsultationResult(
            source="ollama_fallback",
            answer=answer or "Unable to find a solution at this time.",
            success=bool(answer),
        )

    def should_use_codex(self, problem: str, error: str) -> bool:
        """
        Ask ChatGPT whether to use Codex CLI.
        Falls back to True if ChatGPT unavailable.
        """
        prompt = (
            f"Forge is stuck on this problem after 3 attempts. "
            f"Should I use Codex CLI to solve it, or try a different approach?\n\n"
            f"Problem: {problem}\nError: {error}\n\n"
            "Reply with ONLY valid JSON: "
            '{"use_codex": true/false, "alternative": "..." or null}'
        )
        raw = self.ask_chatgpt(prompt)
        if not raw:
            logger.info("[Consultant] ChatGPT unavailable — defaulting to Codex")
            return True

        try:
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            if m:
                data = json.loads(m.group(0))
                use = bool(data.get("use_codex", True))
                self.alternative_approach = data.get("alternative")
                return use
        except Exception:
            pass
        return True


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_consultant: Optional[Consultant] = None


def get_consultant() -> Consultant:
    global _consultant
    if _consultant is None:
        _consultant = Consultant()
    return _consultant
