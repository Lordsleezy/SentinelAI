# SentinelAI

SentinelAI is a local autonomous AI operations platform that routes user tasks through supervised workers, guards privileged actions with approval gates, and runs a GitHub bounty pipeline for finding and queuing repair opportunities.

## Architecture

- **OpenClaw** — user-facing message handler for desktop, phone, and API requests. It owns notifications and approval gates.
- **Orchestrator** — parses tasks, routes them to registered workers, and pauses Forge work until approval is granted.
- **Workers** — Forge builds new tools, Web handles search and page/GitHub lookups, Guardian scans files/secrets, and Repair drives repository fixes.
- **Revenue Pipeline** — discovers GitHub bounty/good-first-issue opportunities, scores them, logs them to SQLite, and queues repair work.
- **Desktop App** — Electron shell plus Flask API at `http://127.0.0.1:5001` for status, approvals, tools, tasks, and revenue monitoring.

## Setup

Prerequisites:

- Python 3.10+
- Node.js
- Ollama, ideally with the configured local coding model available
- Git and, for live PR submission, GitHub credentials in `.env`

Install:

```bash
cd ~/Desktop/SentinelAI
pip install -r requirements.txt
python -c "import db; db.init_db()"
```

Run with the Electron shell when available:

```bash
npm start
```

Fallback runtime if Electron has issues:

```bash
python scripts/launch.py
```

Dry-run launcher check:

```bash
python scripts/launch.py --dry-run
```

## Approval Gates

Forge is intentionally gated. When SentinelAI cannot route a task to an existing worker, the orchestrator creates a pending `forge_start` approval through OpenClaw and stops. Approve it in the UI or via `/api/approvals/resolve`; only then can the orchestrator resume the task and call Forge.

## Revenue

The bounty pipeline searches GitHub for open bounty and good-first-issue issues, filters out issues with competing PRs or missing README context, scores the remaining work by language, tests, description quality, and repo metadata, then queues the top repair candidates. Monitor it through `/api/revenue/status` or the desktop dashboard.
