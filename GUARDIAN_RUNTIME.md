# Guardian Runtime (Brain)

Module: `workers/guardian/runtime_manager.py` (wraps `guardian_runtime_manager.py`)

## API

- `GET /api/guardian/runtime` — `brain` object with friendly fields
- `POST /api/guardian/runtime/model` — set selected model
- `POST /api/guardian/runtime/install` — `ollama pull <model>`

## UI fields

| Field | Description |
|-------|-------------|
| Guardian Brain | Product name for local AI |
| Current model | Friendly name (e.g. Dolphin 3 8B) |
| Status | Ready / Loading / No Guardian Brain installed |
| GPU | RTX / NVIDIA detection via nvidia-smi |
| Memory | VRAM usage when available |

## Supported families

Dolphin, Qwen, DeepSeek, Llama, Mistral, Hermes — user selects from installed Ollama tags; never hardcoded in pipeline.

## Config

`config/guardian_models.json` — `selected_model`, `ollama_url`, `gpu_enabled`
