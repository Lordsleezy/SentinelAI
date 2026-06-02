# Auto Install System

## Principles

1. **Silent by default** — Tier 1 and Tier 2 install without user prompts when possible.
2. **Explicit on failure** — Errors surface in Log, Tasks stage, and chat (never idle after “Install now?”).
3. **Chat confirmation** — When launch needs Godot, `_pending_godot_install` is set; user “yes” triggers `install_godot()` + `launch_latest()`.

## Install entry points

| Capability | Installer |
|--------------|-----------|
| godot | `builders/runtime/godot_runtime.install_godot()` |
| Guardian tools | `workers/guardian/bootstrap_manager.run_bootstrap()` |
| ollama_models | `workers/guardian/runtime_manager.pull_model()` |

## Forge auto-install

Before generation, `ForgeBuildEngine` calls `CapabilityManager.ensure_for_build_type()`. On launch failure for Godot, `_run_forge_build` retries install + launch once before emitting `forge_complete` with `success: false`.

## UI

- Godot overlay: `POST /api/builder/runtime/godot/install`
- Accepts `ok` or `status: "ok"` in JSON response
