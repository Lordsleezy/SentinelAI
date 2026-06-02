# Forge Foundation

## Forge Build Engine

`builders/forge_engine.py` is the orchestration layer for Sentinel builds (foundation for **Forge** product features).

### Responsibilities

1. **Builder routing** — `route_build()` + specialist builders
2. **Verification** — structure/runtime checks before "Build Complete"
3. **Artifact management** — extended registry fields
4. **Repair** — one Aider retry if verification fails
5. **OpenHands hook** — optional worker when CLI available

### Artifact Fields (new)

| Field | Example |
|-------|---------|
| `builder_used` | Godot |
| `project_type` | GAME |
| `verification_status` | verified / failed |
| `build_logs` | scaffold summary |
| `launch_command` | `godot --path "..."` |

### Future (Forge roadmap)

- Device testing (Android APK install + launch)
- Sentinel Vision UI testing
- Autonomous debug loops via OpenHands
- CI-style rebuild on verification failure

## Usage

```python
from builders.forge_engine import ForgeBuildEngine

engine = ForgeBuildEngine(socketio)
result = engine.build("Build Flappy Bird", output_dir=None)
```

Logs always include `[BUILDER] Route: <TYPE>`.
