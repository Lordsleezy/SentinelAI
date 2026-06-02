# Forge Execution Pipeline

A build is **complete** only when the application is runnable.

## Stages (9)

| # | Stage | Module |
|---|--------|--------|
| 1 | Planning | `builders/router.route_build` |
| 2 | Dependency Check | `core/capabilities/capability_manager` |
| 3 | Dependency Install | `runtime_installer` |
| 4 | Generate | Specialized builders / OpenHands |
| 5 | Build | Scaffold / compile hooks |
| 6 | Verifying | `builders/common/verify` |
| 7 | Launch | `builders/launch_verifier` + `artifact_registry.launch_artifact` |
| 8 | Self Repair | Python/Aider fallback (verify fail) |
| 9 | Complete | Artifact register + `forge_complete` |

## Success criteria

```python
result.verification.verified  # structure / runtime checks
result.launch_verified        # process started or dev server up
forge_complete.build_complete # both true
```

## Failure

`forge_complete.success: false` with `error` describing verify or launch failure. Godot missing emits `launch_dependency_prompt` and sets chat pending install flag.

## Tasks tab

`sentinel_task_id` updates `current_stage` and `progress` from `_on_progress` and launch/register phases.
