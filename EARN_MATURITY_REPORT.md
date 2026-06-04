# Earn Maturity Report

**Date:** 2026-06-02  
**Scope:** Earn discovery, research mode, monetization path

---

## Vision Alignment

Earn should support: **Discovery → Research → Validation → Evidence → Submission Draft** with **no automatic submission**.

---

## Current State

### Production-shaped

| Capability | Module | API |
|------------|--------|-----|
| Program discovery | `workers/earn/program_discovery.py` | `/api/earn/discovery/*` |
| Dashboard | `dashboard_service.py` | `/api/earn/discovery/dashboard` |
| Research pipeline | `workers/earn/research/` | `/api/earn/research/start` |
| In-scope Guardian recon | `research/guardian_recon.py` | Internal |
| Evidence vault | `research/store.py` | `/api/earn/research/.../evidence` |
| Tests | `run_earn_research_tests.py` | Local |

### Partial

| Capability | Status |
|------------|--------|
| Freelance scanners | RemoteOK works; Upwork/Freelancer env-gated |
| Legacy background scan | `background_scan_loop` — DB opportunities, separate from research vault |
| Earn orb panel vs `earn_window.html` | Dual UI surfaces |
| Main chat routing | Keyword → placeholder text (**fixed toward execution** via unified router) |

### Stub / intentional

| Capability | Status |
|------------|--------|
| Phase 10 submission | `placeholders.py` — drafts null by policy |
| HackerOne authenticated API | Public mirror only |
| Auto payout / submit | Not planned |

### Separate from platform Learning Engine

- `learning.py` at repo root = **PR outcome learning** for open-source earn — keep; document distinction in `LEARNING_ENGINE_ARCHITECTURE.md`.

---

## Maturity Scorecard

| Phase | % | Notes |
|-------|---|-------|
| Discovery | 85% | Cached mirror, dashboard |
| Research | 75% | Full pipeline, Guardian recon |
| Validation | 50% | Human status on findings |
| Evidence | 70% | Vault + uploads |
| Submission draft | 15% | Placeholders only |
| Unified Sentinel chat | 40% | Routing improvement in progress |

---

## Integration with Sentinel Platform

| Integration | Status | Action |
|-------------|--------|--------|
| Capability domain `EARN` | **Added** to registry | Research deps: ollama, guardian tools |
| Unified chat “research Twilio” | **Router hook** | Parse program → `run_research_pipeline` |
| Findings | Separate vault | Bridge to Guardian findings center (export) |
| Tasks tab | Works for research sessions | Show stage + session id |
| Memory | Vault markdown | Obsidian-compatible paths |

---

## Next Milestones

### P0

1. Main chat: “research &lt;program&gt;” starts pipeline with TaskContext `source=earn`.
2. Discovery picker in chat response (top 3 program matches).

### P1

3. Submission draft templates (markdown, no auto-send).
4. Unified findings export for report writing.

### P2

5. HackerOne API key support (optional config).
6. Freelance aggregator behind single `/api/earn/jobs` facade.

### P3

7. Merge earn research UI into Earn tab only; document `earn_window.html` as dev tool.

---

## What Not To Do

- Rebuild `program_discovery` or research pipeline from scratch.
- Auto-submit reports.
- Remove Earn bottom-nav tab.

---

## Related Docs

- `EARN_RESEARCH_MODE.md` — operator guide
- `ARCHITECTURE_AUDIT_REPORT.md` — system context
- `ORCHESTRATION_ARCHITECTURE.md` — routing
