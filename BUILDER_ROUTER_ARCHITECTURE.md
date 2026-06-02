# Builder Router Architecture

**Branch:** `feature/specialized-builders`

## Overview

Sentinel no longer sends every build request to Aider. The **Forge Build Engine** (`builders/forge_engine.py`) classifies the request, routes to a specialist builder, verifies output, registers an artifact, and falls back to **Python/Aider** only when needed.

## Flow

```
User: "Build Flappy Bird"
        ↓
builders/router.py  →  [BUILDER] Route: GAME
        ↓
builders/game_builder/godot_builder.py
        ↓
builders/common/verify.py
        ↓
workers/artifacts/artifact_registry.py
        ↓
Launch: godot --path <project>
```

## Build Types

| Type | Triggers | Builder | Output |
|------|----------|---------|--------|
| GAME | flappy, bird, game, godot, arcade | Godot | `project.godot`, scenes, GDScript |
| ANDROID | android, apk, kotlin, compose | Android | Gradle + Compose |
| WEB | website, next.js, react, dashboard | Next.js | `app/page.tsx`, Tailwind |
| DESKTOP | calculator, electron, desktop app | Electron | `package.json`, `main.js` |
| PYTHON | script, cli, utility | Aider | `.py` projects |
| UNKNOWN | other build requests | Aider (fallback) | Python |

## Integration Points

- `desktop_app._run_forge_build()` — single entry for all forge builds
- `api_chat` APPROVE flow — Task Manager stages via `on_progress`
- `/api/forge/request` — same engine
- `/orchestration/chat` build shortcut — same engine
- Launch intents (`launch it`) — unchanged; reads artifact `launch_command`

## Task Stages (Tasks panel + `[BUILDER]` log)

Stage 1/5 Planning → 2/5 Generating → 3/5 Testing → 4/5 Verifying → 5/5 Registering artifact → Launch Ready

`Build complete` is emitted only after verification, artifact registration, and launch metadata are saved.

Log filter: **BUILDER** (also matches `[BUILDER]` lines under forge).

Status queries (`status`, `progress`, `any updates`) report active build before Guardian/Earn.

## Files

```
builders/
  router.py
  forge_engine.py
  common/          types, verify, logging, openhands_worker
  game_builder/
  android_builder/
  web_builder/
  desktop_builder/
  python_builder/
```
