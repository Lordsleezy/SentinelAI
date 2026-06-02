# Capability Architecture

Sentinel treats **capabilities** as first-class dependencies. Every feature domain (GAME, WEB, GUARDIAN, AI, …) declares required tools; nothing runs until they are checked, installed if missing, and verified.

## Layout

```
core/capabilities/
  capability_registry.py   # Catalog + tiers + domain → capability ids
  capability_manager.py      # ensure_for_build_type(), status panels
  runtime_validator.py       # Per-capability health probes
  runtime_installer.py       # Delegates to Godot, Guardian bootstrap, Ollama, …
```

## Flow

```
User task → CapabilityManager.ensure_*()
         → validate each id
         → missing? → runtime_installer.install_capability()
         → re-validate → continue or fail with exact error
```

## Install tiers

| Tier | When | Examples |
|------|------|----------|
| 1 Required | Bundled with Sentinel installer | Python, Git, Node, Guardian core tools |
| 2 Recommended | First launch background thread | Godot, Playwright, ZAP |
| 3 Optional | On demand when user requests feature | Android SDK, Unity, large models |

## API

- `GET /api/capabilities/status` — Builder Status Center data
- `GET /api/builder/status` — Same panels (capability-backed)

See also: `RUNTIME_MANAGEMENT.md`, `AUTO_INSTALL_SYSTEM.md`, `FORGE_EXECUTION_PIPELINE.md`, `PREINSTALLED_DEPENDENCIES.md`.
