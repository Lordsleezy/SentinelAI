# Model Router

## Goal

**One Sentinel personality.** Internal models switch by task type; the user never selects or sees “which AI.”

---

## Current State (audit)

| Module | Role | Wired to `/api/chat`? |
|--------|------|------------------------|
| `workers/orchestration/model_selector.py` | Tier table (Ollama + Claude API) | **No** — pipeline only |
| `workers/orchestration/confidence.py` | Ollama → Claude escalation | Pipeline only |
| `desktop_app._chat_quick_response()` | Ollama → Claude → canned | **Yes** (general chat) |
| `models/model_manager.py` | `get_model_for_task()` | `orchestrator.py` only |
| `workers/aider_engine.py` | Own model env | Forge/Aider path |
| `workers/orchestration/task_decomposer.py` | `qwen2.5-coder:14b` default | Decomposer only |

**Gap:** Conflicting defaults (`qwen3:8b` vs `qwen2.5-coder:14b`).

---

## Target Architecture

```
workers/sentinel/model_router.py
        │
        ├── reads config/model_config.json (preferred + fallback per role)
        ├── checks Ollama /api/tags (availability)
        ├── optional VRAM heuristic (future: GPU detect from guardian runtime)
        └── returns ModelRoute { provider, model, role, fallback }
```

### Roles

| Role | Use | Preferred | Fallback |
|------|-----|-----------|------------|
| `general_chat` | Conversational `/api/chat` | Local general model | Claude Haiku API |
| `builder` | Aider / code generation | `qwen2.5-coder:*` | Claude Sonnet API |
| `guardian` | Security analysis | Security-tuned local or Sonnet | General local |
| `research` | Earn / learning research | Reasoning model | General local |
| `vision` | Camera / image (future) | `llava` or cloud vision | Skip / text-only |
| `decomposer` | Plan generation | Coder model | General local |

---

## Requirements Checklist

| Requirement | Status |
|-------------|--------|
| Preferred model per role | **Config file** — extend `config/model_config.json` |
| Fallback model | **In ModelRouter** |
| Availability checks | **Partial** — `ModelSelector._get_available_ollama_models()` |
| VRAM checks | **Not implemented** |
| Runtime loading | Ollama pull via existing `runtime_manager.pull_model` |
| Idle unload | **Not implemented** (Ollama keeps models resident) |

---

## Federation (enhancement layer)

Claude/ChatGPT via:

- `workers/consultation/consultant.py` (SentinelWeb)
- `confidence.call_claude_api()` (API key)

**Sentinel must run without them.** Router falls back to local Ollama always.

---

## Implementation

**Facade:** `workers/sentinel/model_router.py` wraps `ModelSelector` and adds role-based `route(role: str) -> dict`.

**Do not delete** `model_selector.py` — extend via facade.

**Next:** Single import in `_chat_quick_response`, `TaskDecomposer`, and `AiderEngine` env setup.
