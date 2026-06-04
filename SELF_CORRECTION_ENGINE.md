# Self-Correction Engine (Phase 2A)

**Path:** `core/sentinelscrub/self_correction/`

## Pipeline integration

On any pipeline failure, the engine runs:

```
Execute → fail
  → Diagnose (classify_failure)
  → Capture (screenshot, terminal, browser state)
  → Repair memory lookup OR research repair hypothesis
  → Apply repair action
  → Record outcome in repair_memory.db
  → Retry pipeline (up to 5 attempts)
  → Verify → Complete
```

No user intervention required unless `approval_blocked`.

## Modules

| File | Role |
|------|------|
| `classifier.py` | Maps errors to `FailureClass` + signature |
| `failure_capture.py` | `FailureBundle` — logs, screenshot, stderr, browser excerpt |
| `repair_memory.py` | SQLite `repair_memory.db` — patterns + success_rate |
| `self_correction_engine.py` | `run_correction_cycle()` orchestration |

## Failure classes

- auth_failure, network_failure, provider_failure  
- missing_dependency, missing_environment_variable  
- schema_failure, deployment_failure, browser_failure  
- rate_limit, approval_blocked, unknown  

## Capture on failure

1. Terminal stdout/stderr from last desktop command  
2. Playwright screenshot → `data/sentinelscrub/screenshots/`  
3. Page URL, title, body text excerpt  
4. Audit log entry (no secrets)  

## Repair hypothesis

1. **Repair memory hit** — apply stored `repair_action` (e.g. `DROP POLICY IF EXISTS`)  
2. **Else** — research API + provider docs → first `required_action` or classifier hint  
3. **Apply** — desktop command, env guidance, or custom `apply_repair` callback  

## Configuration

- Max retries: `SelfCorrectionEngine(max_retries=5)`  
- Wired in `SentinelScrubEngine._run_pipeline`
