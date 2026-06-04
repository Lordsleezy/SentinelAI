# Architecture Audit Report

**Date:** 2026-06-02  
**Branch context:** `feature/capability-runtime-foundation` + prior Guardian/Earn work  
**Method:** Read-only audit of code, docs, and recent architecture commits. **No subsystem rebuilds.**

---

## Executive Summary

SentinelAI is transitioning from **parallel subsystems** (Chat, Guardian panel, Forge, Earn panel, Memory tab) toward a **unified orchestrator**. The **outcome-based builder path** (capabilities → forge → launch verify) is the most mature vertical. **Unification gaps** are concentrated in chat routing (two endpoints, placeholder worker responses), model policy fragmentation, and federation/memory wiring.

**Rule:** Extend existing modules. Do not delete Guardian, Earn, Memory, Builder, or working APIs.

---

## What Exists (by area)

### Core platform (`core/`)

| Component | Path | Status |
|-----------|------|--------|
| Capability registry | `core/capabilities/capability_registry.py` | **Works** — 31+ capabilities, domains GAME/WEB/DESKTOP/ANDROID/AI/GUARDIAN/CORE/BUILD |
| Capability manager | `core/capabilities/capability_manager.py` | **Works** — ensure, install, status panels |
| Runtime validator | `core/capabilities/runtime_validator.py` | **Partial** — strong for godot/node/guardian core; fallback “assumed optional” for unknown ids |
| Runtime installer | `core/capabilities/runtime_installer.py` | **Partial** — Godot + Guardian bootstrap + Ollama pull; Node/Android manual |
| Learning (new) | `core/learning/learning_engine.py` | **Skeleton** — registry + research workflow (see `LEARNING_ENGINE_ARCHITECTURE.md`) |
| Unified routing (new) | `workers/sentinel/unified_router.py` | **New facade** — intent → internal engine (extends keyword routing) |
| Model router (new) | `workers/sentinel/model_router.py` | **Facade** — wraps `workers/orchestration/model_selector.py` |

### Builder / Forge (`builders/`)

| Component | Status |
|-----------|--------|
| `forge_engine.py` (9 stages) | **Works** — planning, deps, generate, verify, launch prep |
| `launch_verifier.py` | **Works** — artifact launch; WEB npm heuristic |
| `build_tracker.py` | **Works** — single active forge build |
| `runtime/godot_runtime.py` | **Works** — bundled rglob, install, chat confirm |
| `common/verify.py` | **Fixed** — Godot fails without binary |
| `common/openhands_worker.py` | **Stub** — always returns None |
| `python_builder` → Aider | **Works** when `aider-chat` installed |
| Template builders (Godot, Next, Electron) | **Works** — scaffolds, not full LLM apps |

### Orchestration (fragmented — **extend, do not replace**)

| Layer | Path | Status |
|-------|------|--------|
| Orb chat | `desktop_app.api_chat()` | **Primary UX** — forge approve, placeholders for earn/home |
| Pipeline chat | `desktop_app.api_orchestration_chat()` | **Partial** — forge without approve; pipeline LLM-only execute |
| Task decomposer | `workers/orchestration/task_decomposer.py` | **Works** — plans only |
| Orchestration pipeline | `workers/orchestration/pipeline.py` | **Incomplete** — no real worker dispatch |
| LangGraph runtime | `orchestration/runtime.py` | **Parallel** — DB workflows |
| Root orchestrator | `orchestrator.py` | **Parallel** — `/api/tasks/submit` |
| Active work | `workers/active_work.py` | **Works** — build > guardian > earn status |
| Task manager | `workers/task_manager.py` | **Works** — JSON tasks, Socket.IO |

### Guardian

| Component | Status |
|-----------|--------|
| `guardian_brain.py` | **Works** — pipeline, tools, chat |
| `bootstrap_manager.py` | **Works** |
| `findings_center.py` (vault JSON) | **Works** |
| `guardian_findings_db.py` (SQLite) | **Works** — parallel store |
| `/guardian/chat` + orb Guardian panel | **Separate UI chat** — must unify *voice*, not necessarily remove panel |
| Core tools httpx/subfinder/katana/nuclei | **Works** |

### Earn

| Component | Status |
|-----------|--------|
| `program_discovery.py` | **Works** — HackerOne mirror cache |
| `workers/earn/research/*` | **Works** — scope → recon → plan → findings vault |
| Phase 10 submission | **Stub** — intentional human-in-loop |
| Freelance scanners | **Partial** — env-gated |

### Memory

| Component | Status |
|-----------|--------|
| `memory_manager_v2.py` | **Works** — hot/warm/cold, `/memory/*` |
| Legacy `memory_manager.py` | **Legacy** — vault markdown layout (**Obsidian-compatible by convention**, no live plugin) |

**Obsidian integration (audit):** There is **no** Obsidian plugin or sync daemon in-repo. Compatibility is **filesystem-level**: markdown under `memory/vault/` (sessions, notes, cold facts, conversations, findings, research, learned capabilities) can be opened as an Obsidian vault. **Keep** this layout; optional future: `.obsidian/` workspace template or export script — not required for platform operation.
| `learning.py` (repo root) | **Earn PR learning** — separate from platform Learning Engine |
| Conversation sync | **Broken ingest** → fixed to call MemV2 `process_conversation` |

### AI Federation

| Component | Status |
|-----------|--------|
| Browser login | **Partial** — Playwright |
| Conversation sync | **Partial** — metadata only |
| Consultant (SentinelWeb) | **Partial** — external `localhost:8766` |
| Unified memory merge | **Missing** — see `AI_FEDERATION_AUDIT.md` |
| Gemini | **Missing** |

### Documentation (recent)

All present and aligned with implementation direction:

- `CAPABILITY_ARCHITECTURE.md`, `RUNTIME_MANAGEMENT.md`, `AUTO_INSTALL_SYSTEM.md`, `FORGE_EXECUTION_PIPELINE.md`, `PREINSTALLED_DEPENDENCIES.md`
- `AI_FEDERATION_AUDIT.md`, `EARN_RESEARCH_MODE.md`, `GUARDIAN_ROADMAP.md`

---

## What Works End-to-End

1. **Forge build (with approval):** User → `/api/chat` → plan → APPROVE → `_run_forge_build` → capabilities → generate → verify → launch → `forge_complete` only if launch verified.
2. **Godot runtime:** Bundled discovery, install API, chat “yes” confirm, auto-retry on launch fail.
3. **Guardian scans:** APIs + brain + bootstrap + Tasks integration.
4. **Earn research:** Discovery dashboard + research pipeline APIs + vault sessions.
5. **Memory tab:** Stats, recall, purge on V2.
6. **Capability validation:** `run_capability_validation.py` passes on dev machine with bundled Godot.

---

## What Is Stubbed

- OpenHands session (`run_openhands_session` → None)
- Pipeline `_execute_subtask` (LLM text only)
- `/api/chat` earn/home/market pre-routes (`_WORKER_RESPONSES` placeholders)
- Federation message body extraction
- Android Tier-3 toolchain auto-install
- Earn submission automation (by design)

---

## What Is Incomplete

| Gap | Recommendation |
|-----|----------------|
| Three orchestrators + two chat endpoints | **Unify behind** `workers/sentinel/unified_router.py`; deprecate duplicate behavior gradually |
| Guardian not in main chat routing | **Route** scan/recon intents in `api_chat` → `GuardianBrain` with Sentinel voice |
| Earn research not in main chat | **Route** “research &lt;program&gt;” → `run_research_pipeline` |
| Model defaults differ across modules | **Centralize** via `workers/sentinel/model_router.py` + `config/model_config.json` |
| Dual findings stores | **Read model** in `FINDINGS_CENTER_ARCHITECTURE.md` |
| Tasks tab missing learning workflows | Register `source=learning` tasks when Learning Engine runs |
| UI: neon Guardian vs professional target | **GUARDIAN_UI_REDESIGN.md** — CSS tokens, keep Orb |

---

## What Should Be Left Alone

- Orb visual / shell identity (explicit constraint)
- Memory tab and Earn tab (bottom nav)
- Guardian Engine code paths (modernize UX, not remove)
- Existing REST APIs (`/api/guardian/*`, `/api/earn/*`, `/memory/*`)
- Security gates and trusted-target flows
- `sentinel_security` package (if present on branch)

---

## Extension Priority (architectural completion)

1. **Unified chat execution** — guardian + earn research from `/api/chat` (implemented in `unified_router` + `api_chat` hooks).
2. **Memory federation fix** — sync → MemV2 (implemented).
3. **Capability domains** — VISION, RESEARCH, EARN (registry extended).
4. **Learning Engine** — unknown task → research → register capability (skeleton + doc).
5. **Model router doc + facade** — single policy file.
6. **Builder maturity** — launch verify for all build types (WEB/Electron hardening).
7. **Findings center** — unify read path, keep logs.

---

## Related Deliverables

| Document | Purpose |
|----------|---------|
| `LEARNING_ENGINE_ARCHITECTURE.md` | Adaptation over refusal |
| `MODEL_ROUTER.md` | Internal model policy |
| `ORCHESTRATION_ARCHITECTURE.md` | Task/tool/capability routing |
| `FINDINGS_CENTER_ARCHITECTURE.md` | Guardian findings model |
| `GUARDIAN_UI_REDESIGN.md` | Professional UI direction |
| `BUILDER_MATURITY_REPORT.md` | Outcome-based builder gaps |
| `EARN_MATURITY_REPORT.md` | Earn roadmap |
