# Self-Healing Model System

How Sentinel detects, repairs, and notifies when the local Ollama stack degrades — without exposing raw errors to beta users.

## Architecture

```
┌─────────────────────┐     every 45s      ┌──────────────────────┐
│ start_self_healing_ │ ──────────────────► │ ModelRuntime.heal()  │
│ monitor (daemon)    │                     └──────────┬───────────┘
└─────────────────────┘                                │
                                                       ▼
                              ┌────────────────────────────────────────┐
                              │ 1. install_ollama (if missing)         │
                              │ 2. ensure_ollama_running               │
                              │ 3. install_required_models (if gap)  │
                              │ 4. validate_inference                  │
                              └────────────────────────────────────────┘
```

Entry: `core/model_runtime/engine.py` — started from `desktop_app.start_backend()`.

## Detection

| Signal | Method |
|--------|--------|
| Service down | `ollama_running()` → HTTP tags endpoint |
| Binary missing | `ollama_installed()` → PATH + Windows Program Files |
| Model gap | `models_status()` vs `required_models()` |
| Validation stale | `ready.json` missing or `validated: false` |

Aggregated: `GET /api/models/readiness`

## Repair (`heal`)

`POST /api/models/heal` with optional `max_retries` (default 2).

Sequential repair:

1. Install Ollama (Windows silent installer when possible)
2. Start service / tray app (poll 90s)
3. Pull only missing **required** models (hardware-filtered)
4. Re-run inference validation and refresh `OLLAMA_MODEL`

Returns `user_message` — never `stderr`, exit codes, or host strings.

## Chat integration

`POST /api/chat`:

- If `!is_ready()` → one `heal(max_retries=1)` attempt
- Still not ready → `503` with `response: user_message()`, `setup_required: true`
- Replaces legacy: *“Check that Ollama is running, or set ANTHROPIC_API_KEY…”*

Quick replies (`_chat_quick_response`) use `active_chat_model()` from validated `ready.json`.

## Notifications

| Surface | Behavior |
|---------|----------|
| Wizard | Phase text on screen 1–2 (`validate-msg`, progress bar) |
| Chat | Friendly single-sentence status |
| Logs | `logger.info/warning` with exception details for support |
| Electron | No CLI dialogs for Ollama (removed from `vitalsCheck`) |

Future: optional `emit_event('model_status', …)` to orb Settings — not required for beta gate.

## State files

| Path | Content |
|------|---------|
| `data/model_runtime/state.json` | phase, pull/install progress |
| `data/model_runtime/ready.json` | validated chat model, timestamp |
| `data/onboarding/first_launch.json` | wizard step progress |

## Failure modes

| Cause | User sees | Auto action |
|-------|-----------|-------------|
| Ollama not installed | “Setting up the local AI runtime…” | Download installer (Windows) |
| Service stopped | “Starting the local AI service…” | `ollama serve` / launch app |
| Model not pulled | “Downloading language models…” | `ollama pull` required tags only |
| Inference timeout | “Sentinel is reconnecting…” | heal + retry |
| Corporate proxy blocks download | “Sentinel could not restore…” | Manual Settings → Models (no stack trace) |

## Operations

- Force heal: `POST /api/models/heal`
- Status: `GET /api/models/readiness`
- Pull progress: `GET /api/models/pull-status`

Restart backend after manual `ollama rm`; self-heal will re-pull required tags on next chat or monitor cycle.
