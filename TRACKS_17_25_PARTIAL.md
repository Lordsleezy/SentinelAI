# Tracks 17-25 Orchestration Pipeline: PARTIAL IMPLEMENTATION

## Status: 3/9 Tracks Complete

This session started the massive orchestration pipeline + Windows installer build.
Due to the extensive scope (9 orchestration tracks + 7 build parts), this is split across sessions.

---

## ✅ COMPLETED THIS SESSION

### **TRACK 17: Task Decomposition Pipeline** ✅
**File:** `workers/orchestration/task_decomposer.py` (185 lines)

**Implemented:**
- ✅ `classify_complexity(user_request)` — Returns SIMPLE or COMPLEX
- ✅ `decompose(user_request)` — Breaks into max 8 subtasks
- ✅ `classify_type(subtask)` — Maps to CODE/WEB/HOME/CALENDAR/etc
- ✅ `route(task_type)` — Pure dict lookup to worker names
- ✅ `generate_plan(user_request)` — Full plan generation with metadata

**Route Map:**
```python
CODE → forge
FILE → forge
WEB → openclaw.web
MEMORY → memory
HOME → home_assistant
CALENDAR → openclaw.calendar
MUSIC → entertainment.spotify
FINANCE → finance.firefly
CAMERA → home.camera_worker
EARN → earn
MARKET → market
GENERAL → ollama_general
```

---

### **TRACK 18: Confidence + Escalation** ✅
**File:** `workers/orchestration/confidence.py` (180 lines)

**Implemented:**
- ✅ `ollama_with_confidence(prompt, model)` — Appends confidence request, parses response
- ✅ Confidence extraction: extracts HIGH/MEDIUM/LOW from Ollama response
- ✅ `call_claude_api(prompt, context)` — Escalates to Claude Haiku on low confidence
- ✅ `call_with_fallback(prompt, context)` — Auto-escalation logic
  - HIGH → return directly
  - MEDIUM → return (self-verification hook ready for Track 19)
  - LOW → escalate to Claude API

**Environment Variable Added:**
`ANTHROPIC_API_KEY=your_key_here` (needs to be added to .env.example)

---

### **TRACK 19: Self-Verification Loop** ✅
**File:** `workers/orchestration/verifier.py` (130 lines)

**Implemented:**
- ✅ `verify(task, result, task_type)` — Returns {passed: bool, reason: str}
- ✅ `execute_with_retry(task, task_type, worker, payload, max_attempts=3)` — Retry loop with verification
- ✅ Escalation on final failure (placeholder - needs Track 18 integration)
- ✅ Graceful timeout handling (15s verification timeout)

**Note:** Worker execution is stubbed - needs wiring to actual worker dispatch system

---

## 🚧 REMAINING TRACKS (6/9)

### **TRACK 20: Chain of Thought for Code Tasks**
**TODO:** Create `workers/orchestration/chain_of_thought.py`

**Needs:**
- `apply_cot_prefix(task, task_type, codebase_context)` — Prepends thinking scaffold
- `extract_code_context(task)` — Scans for file/function names, reads relevant code
- COT templates for CODE/FILE vs GENERAL vs other types

---

### **TRACK 21: RAG - Context Retrieval**
**TODO:** Create `workers/orchestration/rag.py`

**Needs:**
- Install: `pip install chromadb sentence-transformers`
- `index_codebase()` — Walk .py files, chunk by function/class, embed with `all-MiniLM-L6-v2`
- `query(task, n_results=5)` — Semantic search for relevant code
- `get_context_for_task(task)` — Format top results as context string (max 3000 chars)
- Flask routes: `/orchestration/rag/query`, `/orchestration/rag/status`, `/orchestration/rag/reindex`
- Wire into startup: background thread indexing

---

### **TRACK 22: Model Selector**
**TODO:** Create `workers/orchestration/model_selector.py`

**Needs:**
- Model tier definitions (fast_local: qwen2.5-coder:7b, strong_local: 14b, vision_local: llava, cloud_fast: haiku, cloud_strong: sonnet)
- `select(task, task_type, complexity)` — Returns {provider, model, rationale}
- Check Ollama model availability via localhost:11434/api/tags
- Fallback to next available model if selected model not pulled

---

### **TRACK 23: Structured Output Forcing**
**TODO:** Create `workers/orchestration/structured_output.py`

**Needs:**
- `enforce_json(prompt, schema, model)` — Wraps prompt to force JSON output
- JSON parsing with retry on failure
- Schema validation (fill missing keys with None)
- Pre-built schemas: capability_check, task_decomposition, code_task, verification
- **CRITICAL:** Replace plain string parsing in Tracks 17-19 with structured output calls

---

### **TRACK 24: Plan Approval UI in Orb**
**TODO:** Update `orb.html` and `desktop_app.py`

**Needs:**
- Flask: pending_plans dict, plan_id generation
- `/api/chat` handler: detect complex plans, return `{"type": "plan_preview", ...}` before executing
- Routes: `/orchestration/plan/approve/{plan_id}`, `/orchestration/plan/deny/{plan_id}`, `/orchestration/plan/{plan_id}`, `/orchestration/plans/pending`
- orb.html: plan preview panel with numbered subtasks, type badges (CODE, WEB, etc as colored pills)
- Execute/Cancel buttons
- Real-time progress updates via IPC `plan-step-complete` event
- Collapsible result sections per step

---

### **TRACK 25: Full Pipeline Wiring**
**TODO:** Create `workers/orchestration/pipeline.py`

**Needs:**
- `OrchestrationPipeline` class that coordinates ALL components
- `process(user_request, plan_id)` method — Full flow:
  1. Generate/retrieve plan
  2. Return for approval if complex
  3. Execute each subtask with model selection, RAG context, COT, confidence, retry
  4. Broadcast progress to orb
  5. Assemble final response
- `assemble_response(original_request, results)` — Natural language summary
- Wire into `/api/chat` as single entry point
- Initialize at startup: `pipeline.rag.index_codebase()` in background
- Routes: `/orchestration/status`, `/orchestration/test`, `/orchestration/stats`

---

## 📦 DEPENDENCIES TO INSTALL

```bash
pip install chromadb sentence-transformers
```

**Note:** anthropic SDK not needed - using raw httpx to Claude API

---

## 🔄 INTEGRATION CHECKLIST

After all 9 tracks complete:

- [ ] Update `desktop_app.py` startup: initialize pipeline, start RAG indexing
- [ ] Replace `/api/chat` handler with `pipeline.process()`
- [ ] Wire plan approval routes
- [ ] Update orb.html with plan preview UI
- [ ] Add ANTHROPIC_API_KEY to .env.example
- [ ] Import test all modules (no errors)
- [ ] Commit: "feat(tracks-17-25): full orchestration pipeline - decomposition, COT, RAG, confidence, verification, structured output, model routing"

---

## 🏗 BUILD SYSTEM (PART 1-7)

**NOT STARTED YET**

After Tracks 17-25 complete, implement:

### Part 1: Repo Cleanup
- Update .gitignore (only runtime user data excluded)
- Add .gitkeep files
- Commit venv/ and node_modules/
- Push everything

### Part 2: Setup Wizard
- Create `desktop-shell/setup_wizard.html` (9-page wizard)
- Wire into main.js first-run detection
- Write .env to userData on completion

### Part 3: PyInstaller Backend
- Create `build_backend.spec`
- Create `scripts/build_backend.bat`
- Bundle backend to `backend_dist/`

### Part 4: Electron Builder
- Update package.json with electron-builder config
- Create icon.ico (programmatically)
- Create `scripts/build_installer.bat`
- Output: `installer_dist/SentinelAI Setup.exe`

### Part 5: GitHub Actions
- Create `.github/workflows/build.yml`
- Auto-build on push to master and tags

### Part 6: Self-Extending Capability System
- `capability_registry.json`
- `workers/capability/registry.py`
- `workers/capability/gap_detector.py`
- `workers/capability/capability_finder.py` (PyPI + GitHub search)
- `workers/capability/capability_installer.py` (install + wrap + test)
- `workers/capability/capability_builder.py` (Forge integration)
- Flask routes for approval flow
- orb.html capability approval modal
- Add CAPABILITY_DESCRIPTION to all existing workers

### Part 7: Final Wiring
- Update README.md
- Run full build end-to-end
- Final commit + push

---

## 📊 SESSION STATS

- **Tracks completed:** 3/9 (Orchestration)
- **Files created:** 4
- **Lines of code:** ~495
- **Remaining tracks:** 6 (orchestration) + 7 (build system)
- **Estimated remaining time:** 4-6 hours

---

## 🎯 NEXT SESSION ACTION

1. **Complete Tracks 20-25** (orchestration pipeline)
2. **Integrate into desktop_app.py and orb.html**
3. **Test full pipeline with a complex query**
4. **Commit orchestration complete**
5. **Begin build system** (Parts 1-7)

---

**Status: Orchestration pipeline 33% complete. Build system pending.**
