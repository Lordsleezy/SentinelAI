"""Chat prompt construction, memory policy, and audit logging."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]


def _chat_context_log_path() -> Path:
    try:
        from core.app_paths import resolve_data_dir
        return resolve_data_dir() / "logs" / "chat_context.log"
    except ImportError:
        return _ROOT / "data" / "logs" / "chat_context.log"

# Memory sources that must never shape casual chat replies
_CHAT_EXCLUDED_MEMORY_SOURCES = frozenset({
    "forge", "earn", "system", "log", "guardian", "diagnostic", "setup",
    "aider", "worker", "pipeline", "onboarding",
})

_GREETING_RE = re.compile(
    r"^(hi|hello|hey|howdy|yo|sup|good\s+(morning|afternoon|evening)|"
    r"what'?s\s+up|greetings)[\s!.?]*$",
    re.I,
)

_CAPABILITY_RE = re.compile(
    r"^(what\s+can\s+you\s+do|what\s+do\s+you\s+do|help\s+me|capabilities|"
    r"what\s+are\s+you\s+capable\s+of)[\s!.?]*$",
    re.I,
)

_CONVERSATIONAL_REPLIES: Dict[str, str] = {
    "hi": "Hi! I'm Sentinel. How can I help you today?",
    "hello": "Hello! I'm Sentinel — your personal AI assistant. What would you like to work on?",
    "hey": "Hey! I'm Sentinel. What can I help you with?",
    "howdy": "Howdy! I'm Sentinel. What would you like to do today?",
    "yo": "Hey! I'm Sentinel. How can I help?",
    "sup": "Hi! I'm Sentinel. What can I help you with?",
    "greetings": "Hello! I'm Sentinel. How can I help you today?",
}

_CAPABILITY_REPLY = (
    "I'm Sentinel, your personal AI assistant. I can help with everyday questions, "
    "weather and market lookups, remembering things you ask me to save, building software "
    "when you describe a project, security assessments when you name a target, and research "
    "tasks you want tracked. Just tell me what you'd like in plain language."
)

_BETA_SYSTEM_RULES = """
Beta conversation rules (always follow):
- Reply as Sentinel only — warm, concise, user-facing language.
- Never mention internal workers, routers, logs, diagnostics, memory tags, APIs, or setup steps.
- Never paste debugging, helpdesk, or developer instructions unless the user explicitly asks for technical troubleshooting.
- If the user greets you, greet them back briefly — do not list tools or past session noise.
- Do not reference [Memory context] labels or bracketed source prefixes in your reply.
"""


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_user_message(message: str) -> str:
    return re.sub(r"\s+", " ", (message or "").strip())


def normalize_greeting_key(message: str) -> str:
    s = normalize_user_message(message).lower()
    s = re.sub(r"[^\w\s]", "", s)
    return s.strip()


def is_simple_greeting(message: str) -> bool:
    msg = normalize_user_message(message)
    if not msg or len(msg) > 40:
        return False
    return bool(_GREETING_RE.match(msg))


def is_capability_question(message: str) -> bool:
    msg = normalize_user_message(message)
    if not msg:
        return False
    return bool(_CAPABILITY_RE.match(msg))


def should_attach_memory(message: str) -> bool:
    """Skip memory for short/social messages — prevents log/forge contamination."""
    msg = normalize_user_message(message)
    if len(msg) < 12:
        return False
    if is_simple_greeting(msg) or is_capability_question(msg):
        return False
    try:
        from workers.orchestration.task_decomposer import is_conversational_input
        if is_conversational_input(msg):
            return False
    except Exception:
        pass
    return True


def try_conversational_reply(message: str) -> Optional[str]:
    """Deterministic replies for greetings and capability questions."""
    key = normalize_greeting_key(message)
    if key in _CONVERSATIONAL_REPLIES:
        return _CONVERSATIONAL_REPLIES[key]
    if is_simple_greeting(message):
        return "Hi! I'm Sentinel. How can I help you today?"
    if is_capability_question(message):
        return _CAPABILITY_REPLY
    return None


def filter_memory_lines(context: str) -> str:
    if not context:
        return ""
    lines = []
    for line in context.splitlines():
        low = line.lower()
        if any(x in low for x in ("[forge]", "[earn]", "[system]", "[log]", "diagnostic", "helpdesk", "api/debug")):
            continue
        if any(x in low for x in ("ollama", "wizard", "settings →", "settings->", "worker:", "routing:")):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def build_system_prompt(base_system: str, memory_context: str = "", tools_context: str = "") -> str:
    parts = [base_system.strip(), _BETA_SYSTEM_RULES.strip()]
    mem = filter_memory_lines(memory_context)
    if mem:
        parts.append("Relevant user context (use subtly; do not quote verbatim or mention sources):\n" + mem)
    if tools_context:
        parts.append("Tools context (internal — do not expose to user):\n" + tools_context.strip())
    return "\n\n".join(parts)


def log_chat_context(
    *,
    user_message: str,
    memory_context: str = "",
    system_prompt: str = "",
    tools_context: str = "",
    route: str = "",
    provider: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    log_path = _chat_context_log_path()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    entry = {
        "ts": _utc(),
        "user_message": user_message,
        "memory_context": memory_context[:4000] if memory_context else "",
        "system_prompt": system_prompt[:8000] if system_prompt else "",
        "tools_context": tools_context[:2000] if tools_context else "",
        "route": route,
        "provider": provider,
        "extra": extra or {},
    }
    try:
        with log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def prepare_chat_llm_input(
    message: str,
    base_system: str,
    memory_context: str = "",
    tools_context: str = "",
) -> Tuple[str, str]:
    """Return (user_prompt, full_system_prompt) for the LLM."""
    user_prompt = normalize_user_message(message)
    system = build_system_prompt(base_system, memory_context=memory_context, tools_context=tools_context)
    return user_prompt, system
