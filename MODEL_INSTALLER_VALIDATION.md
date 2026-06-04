# Model Installer Validation

Production checklist for Sentinel’s local AI stack (Ollama + Llama + Dolphin) on a fresh Windows beta machine.

## Scope

| Component | Responsibility |
|-----------|----------------|
| `core/model_runtime/engine.py` | Detection, install, pull, validation, heal |
| `core/model_manager/engine.py` | Hardware-aware Llama/Dolphin recommendations |
| `core/dependency_manager/engine.py` | Ollama component install on Windows |
| `desktop_app.py` | `/api/models/*`, `/api/setup/*` |
| `desktop-shell/setup_wizard.html` | Guided first-run UI |

## Startup detection

On backend start and on `/api/models/readiness`:

1. **Ollama installed** — `ollama` on PATH or `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`
2. **Ollama running** — `GET http://127.0.0.1:11434/api/tags` (IPv4; avoids Windows `localhost` → `::1` failures)
3. **Required models** — from `ModelManager.recommend()`:
   - **Llama** (fallback/general): always one of `llama3.2:3b`, `llama3.1:8b`, …
   - **Dolphin** (primary agent): only when RAM/VRAM/disk thresholds allow; never pulls oversized models on low-end hardware
4. **Validated** — short `/api/generate` test; result stored in `data/model_runtime/ready.json`

## Automatic Ollama install (Windows)

| Step | Behavior |
|------|----------|
| Download | `OllamaSetup.exe` from `https://ollama.com/download/OllamaSetup.exe` with progress in `data/model_runtime/state.json` |
| Install | Silent flags: `/SILENT`, `/VERYSILENT`, `/S` |
| Start | Launches Ollama app or `ollama serve`; polls up to 90s |
| Non-Windows | Returns guided `open_url` action (no silent installer) |

API: `POST /api/setup/install-ollama`

## Automatic model install

| Rule | Implementation |
|------|----------------|
| Hardware fit | `ModelManager.recommend()` from RAM, VRAM, free disk |
| No extras | Only `llama` + optional `dolphin` tags; catalog entries not in recommendation are never pulled |
| Progress | `GET /api/models/pull-status` — model name, `size_gb`, `percent`, message line from `ollama pull` |
| Background pull | `POST /api/setup/pull-model` → `install_required_models()` |

## Validation gate

Before chat or wizard completion:

```
POST /api/setup/validate
  → local generate ("Reply with exactly the word READY…")
  → non-empty response
  → sets OLLAMA_MODEL env + ready.json
```

`POST /api/setup/complete` calls `mark_setup_complete()` and refuses `200` until `readiness.ready === true`.

## Beta validation script (manual)

On a clean VM after `SentinelAISetup.exe`:

```powershell
# 1. Readiness
Invoke-RestMethod http://127.0.0.1:5001/api/models/readiness | ConvertTo-Json -Depth 5

# Expect: ready=true, ollama_installed=true, ollama_running=true, all_required_models=true, validated=true

# 2. Inference
Invoke-RestMethod -Method POST http://127.0.0.1:5001/api/setup/validate

# 3. Chat (with auth if enabled)
Invoke-RestMethod -Method POST http://127.0.0.1:5001/api/chat -Body '{"message":"hello"}' -ContentType application/json
```

Pass criteria:

- No user-facing string containing `ECONNREFUSED`, stack traces, or `ollama serve` CLI instructions
- Chat returns `200` with a non-empty `response`, not `model_unavailable`

## Self-heal smoke test

1. Stop Ollama tray app.
2. Wait ~45s (monitor interval).
3. `GET /api/models/readiness` — should return to `ollama_running` without user action, or friendly `user_message` while repairing.

## Known limits

- Ollama silent install requires outbound HTTPS and admin rights on some corporate images.
- First model pull size is network-bound; wizard polls up to 60 minutes.
- Anthropic fallback remains optional via `ANTHROPIC_API_KEY`; beta path assumes local models only.
