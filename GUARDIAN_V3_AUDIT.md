# Guardian v3 — Current State Audit

**Date:** 2026-06-02  
**Scope:** Bootstrap, tool installer, task tracking, reporting, AI runtime, authorization, tool status panel.  
**Constraint:** No code changes were made before this document.

---

## Executive Summary

Guardian has a **working core pipeline** (Subfinder → Amass → httpx → Katana → Nuclei → ZAP → Ollama analysis → Markdown report) with **stage enter/exit logging** and **partial Tasks integration**. Significant gaps remain versus v3: **no dedicated Guardian runtime manager**, **four-tool bootstrap only**, **no extended pipeline tools in execution**, **threat intel and findings DB are stubs**, **dual Guardian code paths**, and **task UI lacks Guardian-specific expandable artifacts**.

---

## 1. Guardian Bootstrap

| Aspect | State | Evidence |
|--------|--------|----------|
| Startup repair | **Working** | `desktop_app.py` daemon thread calls `bootstrap_guardian_core()` |
| Bundled copy from installer_assets | **Working** | `guardian_bootstrap.py` — zip extract, verify binary |
| State persistence | **Working** | `memory/vault/guardian_bootstrap.json` |
| Auto-download | **Partial** | Delegates to `guardian_tool_fetcher.ensure_guardian_core_staged()` |
| Auto-update | **Missing** | No version compare / refresh policy |
| Tools covered | **4 only** | `CORE_TOOL_IDS` = httpx, subfinder, katana, nuclei (`bundled_toolchain.py:23`) |
| Extended tools (naabu, dnsx, ffuf, …) | **Not in bootstrap** | Manifest `installer_assets/guardian_core/manifest.json` lists 4 tools |

**Broken / weak:** Amass, assetfinder, dnsx, naabu, ffuf, gowitness are **not** repaired or downloaded by bootstrap.

---

## 2. Guardian Tool Installer (Fetcher)

| Aspect | State | Evidence |
|--------|--------|----------|
| GitHub latest release download | **Working** | `guardian_tool_fetcher.py` — ProjectDiscovery API |
| Staging to `tools/<id>/` | **Working** | `stage_tool_from_github()` |
| Verify after install | **Partial** | Size check (>50KB); no version string in panel |
| Repair loop | **Via bootstrap** | `_repair_tool()` in bootstrap |
| False positives in status | **Possible** | `diagnose_core_tool` marks installed if **any** PATH exe exists; httpx uses separate `find_projectdiscovery_httpx` (good) |

**Missing:** Unified health probe (executable runs `-version`), auto-update, non-PD tools (gowitness, assetfinder).

---

## 3. Guardian Task Tracking

| Aspect | State | Evidence |
|--------|--------|----------|
| Task creation on scan | **Working** | `guardian_brain._run_full_assessment` → `create_task(..., source="guardian")` |
| Progress updates | **Partial** | `_tp()` updates `progress` + `result_summary`; **no** `current_stage`, **no** `metadata` stage logs |
| Failure marking | **Weak** | Pipeline exceptions still attempt final report; task may stay RUNNING if crash before COMPLETED |
| Tasks UI | **Generic** | `orb.html` `renderTasksTab` shows `current_stage` if set — Guardian rarely sets it |
| Artifacts in task | **Missing** | Report path not added to `files_created`; no expandable logs/reports in Tasks |
| Elapsed / tool running / findings count | **Missing** | Not in `task_manager` schema usage |

---

## 4. Guardian Reporting Pipeline

| Aspect | State | Evidence |
|--------|--------|----------|
| Stage logging | **Working** | `_stage_enter` / `_stage_exit` / `_stage_skip` |
| Final Markdown report | **Working** | `_build_final_report()` — executive summary, tech, findings, risk, recommendations |
| Report file save | **Working** | `memory/vault/guardian_reports/<session_id>.md` |
| Threat intel in report | **Missing** | No OTX/AbuseIPDB/KEV sections |
| Attack surface / recon sections | **Partial** | Assets + endpoints; no dedicated “Attack Surface” / “Recon Results” / “Threat Intel” blocks |
| Report quality metrics | **Missing** | No scoring metadata stored |
| Socket streaming | **Working** | `guardian_response` events per step |

**Pipeline vs spec:** Spec order includes assetfinder, dnsx, naabu, ffuf, Threat Intel — **not executed** in `_run_full_assessment` (only validation → subfinder → amass → httpx → katana → nuclei → zap → AI).

---

## 5. Guardian AI Runtime

| Aspect | State | Evidence |
|--------|--------|----------|
| Backend | **Ollama** | `guardian_config.json` `ollama_url` |
| Model selection | **Tier-based, not user** | `models.fast/reasoning/code` in config; `_classify_task_tier()` |
| Separation from Sentinel chat | **Not enforced** | Same Ollama URL; different config file only |
| Separation from Earn/Builder | **Not enforced** | No dedicated Guardian runtime process |
| GPU / VRAM / inference metrics | **Missing** | No dashboard |
| `[GUARDIAN AI]` log prefix | **Missing** | Uses `[GUARDIAN]` and generic Ollama errors |
| Runtime dashboard API | **Missing** | No `/api/guardian/runtime` |

**Duplicate:** `_call_ollama` (chat) and `_analyze_with_ollama` (pipeline) share one code path without runtime manager.

---

## 6. Guardian Authorization Workflow

| Aspect | State | Evidence |
|--------|--------|----------|
| Confirmation gate | **Removed** | `is_authorized()` always `True`; scans start immediately (`guardian_brain.py:294-295`) |
| In-memory targets | **Legacy** | `authorized_targets` set; not persisted |
| Trusted targets store | **Missing** | No JSON vault store / expiry |
| Config stale flag | **Stale** | `guardian_config.json` `require_target_confirmation: true` |
| API compat | **Present** | `request_authorization` / `confirm_authorization` no-ops |

**v3 gap:** Section 5 requires **persisted trusted targets** and Settings UI — not implemented.

---

## 7. Guardian Tool Status Panel

| Aspect | State | Evidence |
|--------|--------|----------|
| API | **Working** | `/api/guardian/tools/status` → `get_tool_diagnostics()` |
| UI | **Working** | `orb.html` `guardianLoadTools()` — Active pipeline + Roadmap |
| Version column | **Missing** | Only path + status_line |
| Health column | **Missing** | No subprocess health check |
| Threat intel row | **Placeholder** | `status_line: "Phase 5 — planned"` |
| Roadmap false positive risk | **Medium** | `_probe_roadmap_binary` may show ✓ System for unrelated PATH binaries |

---

## Working Systems

1. **GuardianBrain chat + scan trigger** — keyword/mode detection, immediate pipeline start.
2. **Core PD tool wrappers** — Subfinder, httpx (compat parser), Katana, Nuclei, Amass, ZAP.
3. **Pipeline resilience** — per-stage try/except; final report in `finally`.
4. **httpx multi-mode parser** — `httpx_compat.py` (JSONL, plain text, regex).
5. **Bootstrap + fetcher** for 4 core binaries.
6. **Tool status panel** (core + roadmap listing).
7. **FaradayStore SQLite** — basic findings insert from Nuclei.
8. **Socket.IO** — `guardian_response`, `log_event` (type=guardian), task_created/task_update.
9. **Security gates** on `/guardian/chat` and tool run (Sentinel security package).

---

## Broken Systems

1. **Stale config** — `require_target_confirmation: true` contradicts runtime behavior.
2. **Dual Guardian APIs** — `/api/guardian/scan` uses `guardian_worker` (EICAR/file scan), not `GuardianBrain` pipeline.
3. **Task failure states** — abnormal thread death may leave RUNNING tasks.
4. **Earn research vs brain** — separate `workers/earn/research/guardian_recon.py` path (intentional but duplicates tool invocation patterns).

---

## Missing Systems (v3 spec)

| # | System |
|---|--------|
| 1 | Guardian Runtime Manager (user-selectable models, VRAM, dashboard, `[GUARDIAN AI]` logs) |
| 2 | Full toolchain bootstrap (naabu, assetfinder, dnsx, ffuf, gowitness, auto-update) |
| 3 | Full pipeline stages (assetfinder, dnsx, naabu, ffuf, threat intel, structured Running/Failed) |
| 4 | Tasks: stage, elapsed, tool running, findings count, expandable logs/reports/artifacts |
| 5 | Authorized Targets Store + Guardian Settings / Trusted Targets UI |
| 6 | Threat intelligence (OTX, AbuseIPDB, CISA KEV, feeds) |
| 7 | Crypto Threat Intelligence roadmap module |
| 8 | Guardian Findings DB (searchable, exportable, filterable — beyond minimal Faraday schema) |
| 9 | Report sections: Attack Surface, Recon Results, Threat Intel, quality metrics |
| 10 | Structured refusal replacement (partially addressed by removing gate; need structured error responses) |

---

## Duplicate Code Paths

| Path A | Path B | Notes |
|--------|--------|-------|
| `guardian_brain._run_tool_direct` | ToolRegistry wrappers | Two execution styles |
| `guardian_worker.run_guardian_task` | `GuardianBrain._run_full_assessment` | Different products under “Guardian” |
| `httpx_tool` + `httpx_compat` | `_run_curl_check` fallback | Intentional fallback chain |
| `diagnose_core_tool` | Tool class `is_available()` | May disagree on httpx |
| Manifest in bootstrap | Manifest in fetcher | Duplicated `_load_manifest()` |
| In-memory `authorized_targets` | (none persisted) | Dead persistence path |

---

## Technical Debt

1. **Monolithic `guardian_brain.py`** (~1200 lines) — pipeline should be separate module.
2. **Hardcoded model tiers** — not user-selectable Dolphin/Qwen/etc.
3. **WSL fallback in `_run_tool_direct`** — can hang or confuse Windows diagnostics.
4. **Metasploit / ReconFTW in imports** — not in v3 pipeline; adds noise in `tools_available`.
5. **No integration tests for full pipeline** — only httpx parser tests exist.
6. **Roadmap tools shown as missing/planned** while spec requires installation.

---

## Recommended Fixes (implementation order)

1. **GUARDIAN_V3_AUDIT.md** (this document) ✅  
2. `guardian_runtime_manager.py` + config `guardian_models.json` + API + panel dashboard  
3. Extend `CORE_TOOL_IDS` / manifest / bootstrap / fetcher + version/health in diagnostics  
4. `guardian_pipeline_v3.py` — full stage list + task metadata + findings DB writes  
5. `guardian_trusted_targets.py` + settings API + panel trusted targets  
6. `guardian_threat_intel.py` + report sections  
7. `guardian_findings_db.py` — unified schema + export API  
8. `guardian_crypto_intel.py` — roadmap stub + doc  
9. Wire `guardian_brain` to v3 modules; fix config; unify API responses  
10. Tasks UI metadata (minimal orb patch in Guardian-adjacent Tasks rendering)  
11. `run_guardian_v3_validation.py` → **GUARDIAN_V3_VALIDATION.md**

---

## File Reference Map

| Component | Primary files |
|-----------|----------------|
| Brain / pipeline | `workers/guardian/guardian_brain.py` |
| Bootstrap | `workers/guardian/guardian_bootstrap.py` |
| Fetcher | `workers/guardian/guardian_tool_fetcher.py` |
| Bundled resolve | `workers/guardian/bundled_toolchain.py` |
| Registry | `workers/guardian/tools/tool_registry.py` |
| Findings (minimal) | `workers/guardian/tools/faraday_store.py` |
| Tasks | `workers/task_manager.py` |
| Legacy worker | `workers/guardian_worker.py` |
| API | `desktop_app.py` (`/guardian/*`, `/api/guardian/*`) |
| UI | `desktop-shell/orb.html` (Guardian panel, Tasks tab) |
| Config | `config/guardian_config.json` |

---

*Audit complete. Implementation may proceed.*
