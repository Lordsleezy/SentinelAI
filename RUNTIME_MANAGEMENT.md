# Runtime Management

Sentinel owns runtimes end-to-end. Users should not install Godot, Node, or Guardian binaries manually.

## Resolution order (example: Godot)

1. Bundled under `tools/godot/` (recursive `Godot*.exe`)
2. Configured path in `memory/vault/builder_runtime.json`
3. Common Windows install paths
4. `PATH`
5. Auto-install: installer assets → GitHub release download

## Validation

`runtime_validator.validate_capability(id)` returns:

- `installed`, `healthy`, `version`, `path`, `last_verified`

GAME builds **fail verification** if Godot is missing (no more “structure valid without binary”).

## Health in UI

Tasks / Builder Status show per capability: Installed, Version, Health, Last Verified via `CapabilityManager.builder_status_panels()`.
