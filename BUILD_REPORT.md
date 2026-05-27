# Sentinel Earn — Build Report

**Build date:** 2026-05-26  
**Status:** COMPLETE — all modules verified  

---

## Files Created

| File | Lines | Description |
|------|-------|-------------|
| `db.py` | ~240 | SQLite schema + full CRUD for 3 tables |
| `scanner.py` | ~320 | Algora + IssueHunt (Playwright) + GitHub API |
| `prompt_engine.py` | ~390 | 8-technique Ollama prompt pipeline |
| `executor.py` | ~350 | Fork/clone/fix/apply/PR full pipeline |
| `monitor.py` | ~140 | PR status polling, earnings recording |
| `dashboard.py` | ~250 | FastAPI + dark HTML dashboard |
| `main.py` | ~175 | APScheduler entry point + CLI |
| `requirements.txt` | 20 | Pinned dependencies |
| `.env.example` | 22 | All environment variables documented |
| `README.md` | ~180 | Full setup + architecture docs |
| `Makefile` | 30 | install / run / dry-run / dashboard / clean |
| `_test_imports.py` | ~140 | Import + unit tests (dev only) |

---

## Test Results

All 6 modules imported and unit-tested without errors:

```
db.py:            OK  (inserted opp_id=1)
  earnings summary: confirmed=0 pending=0 merge_rate=0%
scanner.py:       OK  (score=7.25, complexity=2.0, amount=$1500.0, bounty_text=$250.0)
  compress_context: 1709 chars from 2 files
  parse plain JSON: confidence=8
  parse fenced JSON: confidence=8
  parse wrapped JSON: confidence=8
  keywords: ['NullPointerException', 'UserService', 'authenticate', 'token', 'None']
  build_fix_prompt:   3969 chars
  build_verify_prompt:1273 chars
  build_retry_prompt: 1493 chars
  build_cx_prompt:    1086 chars
prompt_engine.py: OK
executor.py:      OK  (atomic apply: modified=['foo.py'])
  rollback on bad old_code: OK
monitor.py:       OK  (parse PR URL: facebook/react#123)
dashboard.py:     OK  (FastAPI app title='Sentinel Earn')

====================================================
  ALL IMPORTS AND UNIT TESTS PASSED -- OK
====================================================
```

### Dry-run end-to-end test

```
python main.py --execute-now --dry-run
```

Result: Picked up highest-value opportunity (prettier/prettier issue, $200),
fetched real GitHub issue details, detected language=javascript,
attempted Ollama complexity assessment (failed gracefully — model not yet
pulled, 404 handled with 3-retry exponential backoff), returned dry-run result.
No GitHub writes. No file changes. Zero side effects confirmed.

---

## Architecture Notes

### Database (db.py)

Three tables in `data/sentinel_earn.db`:

```sql
opportunities  — one row per bounty issue found
submissions    — one row per PR submitted (with earnings tracking)
agent_log      — event log for all agent activity
```

WAL journal mode for concurrent FastAPI + scheduler reads. Context manager
wraps every connection with auto-commit/rollback.

### Scanner (scanner.py)

- **Algora.io**: Playwright headless Chromium, multi-selector fallback strategy
  (sites change markup; fallback to `a[href*='/issues/']` link scan)
- **IssueHunt.io**: Same Playwright approach with fallback
- **GitHub Issues API**: 7 search queries covering Python/JS/TS bounty labels,
  rate-limit aware (60s pause on 403), 1.5s spacing between queries
- **Scoring**: 6-factor weighted score (bounty, comments, labels, stars, age, language)
- **Complexity**: Text signal analysis (easy vs hard keywords) + comment count
- **Filters**: Language must be JS/TS/Python, complexity must be <= 5/10

### Prompt Engine (prompt_engine.py)

8 techniques implemented:

1. **Chain-of-thought forcing** — 5-step reasoning block required before any code
2. **Role priming** — "15-year senior engineer" persona prepended to every prompt
3. **Structured output enforcement** — JSON schema enforced, parse-validate-correction
   retry loop (strips markdown fences, relaxed comma handling, outermost-brace extraction)
4. **Context compression** — keyword-hit scoring per file, 50+50+30-keyword-line
   summarisation for long files, hard 32,000-char budget
5. **Self-verification loop** — fix sent back with 4-question critical review;
   "revise" verdict lowers confidence and attaches revision notes
6. **Retry with simplification** — low-confidence first attempt triggers a
   one-line-focus retry prompt
7. **Language-specific rules** — PEP 8/type hints (Python), const/let/=== (JS),
   no-any/interfaces (TS) injected into every prompt
8. **Complexity gating** — model self-rates 1-10 before attempting; >5 = skip

Ollama calls: 180s timeout, 3-retry exponential backoff (1s, 2s, 4s).

### Executor (executor.py)

```
get_top_opportunity() [highest bounty, cx <= 5, status=new]
  → get_issue_details() [GitHub API: body + comments + repo metadata]
  → fork_repo()         [GitHub API: POST /repos/{owner}/{repo}/forks]
  → clone_repo()        [GitPython depth=1, token injected into HTTPS URL]
  → read_repo_files()   [keyword-prioritised, max 20 files, max 50KB each]
  → run_fix_pipeline()  [8-step prompt pipeline]
  → gate: confidence >= 7
  → apply_fixes_atomic()  [snapshot → apply → rollback on any error]
  → commit_and_push()     [new branch, git commit, push to fork]
  → create_pull_request() [GitHub API: POST /pulls]
  → post_issue_comment()  [GitHub API: POST /issues/{n}/comments]
  → db.insert_submission()
  → cleanup_workspace()   [shutil.rmtree]
```

Dry-run mode intercepts at `get_issue_details()` (real HTTP, read-only),
short-circuits before fork/clone/apply/push/PR.

### Monitor (monitor.py)

Polls `list_pending_submissions()` every 30 minutes. For each:
- `state=open` → update status to "open"
- `merged=true` → record earnings = bounty_amount, mark payout_confirmed
- `state=closed, merged=false` → mark rejected

### Dashboard (dashboard.py)

Single-page dark-mode UI:
- Live earnings counter with green glow animation on increase
- 5-stat grid (confirmed, pending PRs, merge rate, opps, submissions)
- Opportunity table (top 25, sortable by bounty)
- Submissions table with PR links
- Activity feed (latest 50 log events)
- Scan Now / Execute Fix action buttons (background tasks via FastAPI)
- Auto-refresh every 10 seconds via `setInterval`

---

## Configuration

Copy `.env.example` to `.env`:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GITHUB_TOKEN` | For PR submission | — | Fine-grained PAT |
| `GITHUB_USERNAME` | For PR submission | — | Your GitHub handle |
| `DRY_RUN` | No | `false` | Safe mode |
| `SCAN_INTERVAL_HOURS` | No | `2` | Scanner frequency |
| `OLLAMA_HOST` | No | `http://127.0.0.1:11434` | Ollama URL |
| `OLLAMA_MODEL` | No | `qwen2.5-coder:14b` | Model name |

---

## Quick Start

```bash
# 1. Pull the model (one-time, ~8GB)
ollama pull qwen2.5-coder:14b

# 2. Install Python deps
pip install -r requirements.txt
python -m playwright install chromium

# 3. Configure
copy .env.example .env
# Edit .env with your GitHub credentials

# 4. Safe test run
python main.py --dry-run --scan-now

# 5. Full agent
python main.py
# Dashboard: http://localhost:8765
```

---

## Known Limitations / Future Work

- **Algora/IssueHunt selectors**: These sites update their markup regularly.
  The fallback link-scan strategy handles this but scraped data may be sparse.
  A future version could use their public APIs when available.
- **Repo stars in GitHub search**: The Search API doesn't return stargazers_count
  in results; it defaults to 0 in scoring. Fetching per-repo adds ~1 API call each.
- **PR conflict handling**: If the fork is behind the upstream, the push may fail.
  A `git rebase` step before push would handle this.
- **Multi-file changes**: The current atomic apply works file-by-file; a future
  version could use a git-based patch approach for more robust application.
- **Ollama context window**: qwen2.5-coder:14b has a 32K context. The 8K-token
  code budget is conservative. Could be expanded for larger fixes.
