# OpenHands Integration

**Repository:** https://github.com/All-Hands-AI/OpenHands

## Role

OpenHands is **not** a replacement for Sentinel. It is an optional **Builder Worker** invoked from `ForgeBuildEngine` before native builders run.

## Workflow

```
Sentinel ForgeBuildEngine
    ↓
run_openhands_session()  (if CLI/docker detected)
    ↓ (if unavailable)
Native specialist builder (Godot, Electron, Next.js, …)
    ↓
Verification
    ↓
Artifact
```

## Current Status

- `builders/common/openhands_worker.py` probes for `openhands` / `docker`
- Returns `None` when unavailable — native builders proceed
- Full session API wiring is incremental; native scaffolds are production path today

## Capabilities (when fully wired)

- Terminal execution
- File editing
- Test / debug / repair loops

## Install (optional)

Follow upstream OpenHands install docs. No Sentinel code changes required beyond the worker module.
