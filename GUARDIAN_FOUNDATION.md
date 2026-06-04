# Guardian Foundation

**Monitor:** `workers/guardian/system_monitor.py`  
**API:** `/api/guardian/dashboard`, `/api/guardian/alerts`

## Real telemetry (psutil)

- CPU and RAM utilization
- Per-mount disk usage (no synthetic values)
- Network byte counters (`net_io_counters`)
- Top processes by CPU
- Sentinel backend process detection (`desktop_app` in cmdline)
- Service probes: TCP port `5001`, HTTP `/api/health/live`

## Dashboard

Settings → **Guardian** panel includes **System Health** and alert cards fed by the monitor.

## Alerting

Threshold-based alerts (CPU/RAM/disk/services) with **remediation suggestions** — stored in-memory ring buffer, exposed via `/api/guardian/alerts`.

## Background sampling

Monitor starts at app boot (`get_guardian_monitor()`), samples every 10s by default.

## Requirements

```bash
pip install psutil httpx
```

Without psutil, the API reports an explicit error — never fake metrics.
