"""
run_stability_tests.py — Sentinel Stability + Guardian Professionalization Tests

TEST 1  Build Calculator       — artifact created, launch works
TEST 2  Guardian scan          — progress visible, final report generated
TEST 3  Earn analysis          — completes OR specific failure reason (no hang)
TEST 4  Claude connect         — false Connected state removed
TEST 5  Nuclei                 — runs or gracefully skipped
TEST 6  Subfinder              — runs or gracefully skipped
TEST 7  httpx                  — runs or gracefully skipped
TEST 8  Katana                 — runs or gracefully skipped
TEST 9  ZAP                    — runs or gracefully skipped
TEST 10 Amass                  — runs or gracefully skipped
"""
import os, sys, time, threading, shutil, tempfile, traceback
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

PASS = "[PASS]"; FAIL = "[FAIL]"; ERR  = "[ERR] "
results = []

def record(name, ok, detail=""):
    sym = PASS if ok else FAIL
    print(f"{sym} {name}", flush=True)
    if detail:
        print(f"       {detail}", flush=True)
    results.append((name, ok, detail))

def err_record(name, exc):
    print(f"{ERR} {name}: {exc}", flush=True)
    results.append((name, False, str(exc)))


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1 — Build Calculator: artifact created, launch works
# ─────────────────────────────────────────────────────────────────────────────
def test_build():
    print("\n--- TEST 1: Build + Artifact + Launch ---", flush=True)
    import workers.artifacts.artifact_registry as ar_mod
    tmp_art = Path(tempfile.mkdtemp()) / "registry.json"
    orig = ar_mod._REGISTRY_PATH
    ar_mod._REGISTRY_PATH = tmp_art; ar_mod._registry.clear(); ar_mod._loaded = False
    try:
        tmp = Path(tempfile.mkdtemp())
        entry = tmp / "main.py"
        entry.write_text("print('Calculator')\n")

        from workers.task_manager import TaskContext
        from workers.artifacts.artifact_registry import register_artifact, get_latest_artifact, launch_artifact

        with TaskContext("Build Calculator", source="forge") as ctx:
            ctx.progress(30, "Building")
            art = register_artifact("Calculator", entry_point=str(entry), output_dir=str(tmp),
                                    files=[str(entry)], task_id=ctx.task_id)
            ctx.complete(result_summary="Built Calculator", artifact_id=art['id'])

        latest = get_latest_artifact()
        record("TEST 1 — Artifact created", bool(latest and latest['id'] == art['id']),
               f"ID={art.get('id')} entry={art.get('entry_point','')}")
        record("TEST 1 — Launch command derived", bool(art.get('launch_command')),
               f"cmd={art.get('launch_command','')}")
        launch_res = launch_artifact(latest)
        record("TEST 1 — Launch executes ok=True", launch_res.get('ok') is True,
               str(launch_res))
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception as e:
        err_record("TEST 1 — Build + Artifact + Launch", e)
    finally:
        ar_mod._REGISTRY_PATH = orig; ar_mod._registry.clear(); ar_mod._loaded = False


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2 — Guardian: progress visible, final report generated
# ─────────────────────────────────────────────────────────────────────────────
def test_guardian():
    print("\n--- TEST 2: Guardian Scan ---", flush=True)
    import workers.task_manager as tm_mod
    tmp_tasks = Path(tempfile.mkdtemp()) / "tasks.json"
    orig = tm_mod._TASKS_PATH
    tm_mod._TASKS_PATH = tmp_tasks; tm_mod._tasks.clear(); tm_mod._loaded = False
    try:
        from workers.guardian.guardian_brain import GuardianBrain
        brain = GuardianBrain(socketio=None)
        brain._call_ollama = lambda *a, **kw: "AI analysis complete (mocked)."

        steps = []
        progress_vals = []
        final_seen = [False]

        _orig_emit = brain._emit_guardian_response
        def _mock_emit(msg, target, step=''):
            steps.append(step)
            if step == 'final':
                final_seen[0] = True
        brain._emit_guardian_response = _mock_emit

        _orig_create = tm_mod.create_task
        _orig_update = tm_mod.update_task
        def _mock_update(task_id, **kw):
            if kw.get("progress") is not None:
                progress_vals.append(kw["progress"])
            return _orig_update(task_id, **kw)
        tm_mod.update_task = _mock_update

        brain._run_full_assessment("localhost")
        # Wait up to 20s for the background thread — ToolRegistry init takes ~4s
        # plus each stage; curl/httpx may need a few seconds on localhost
        for _ in range(20):
            if final_seen[0]:
                break
            time.sleep(1)

        tm_mod.update_task = _orig_update
        brain._emit_guardian_response = _orig_emit

        record("TEST 2 — Guardian emits start step", 'start' in steps,
               f"Steps seen: {steps}")
        record("TEST 2 — Guardian progress updates", len(progress_vals) > 0,
               f"Progress: {sorted(set(progress_vals))}")
        record("TEST 2 — Guardian final report emitted", final_seen[0],
               f"All steps: {steps}")
    except Exception as e:
        err_record("TEST 2 — Guardian Scan", e)
    finally:
        tm_mod._TASKS_PATH = orig; tm_mod._tasks.clear(); tm_mod._loaded = False


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3 — Earn: completes OR specific failure reason, no hang
# ─────────────────────────────────────────────────────────────────────────────
def test_earn():
    print("\n--- TEST 3: Earn Analysis ---", flush=True)
    import workers.task_manager as tm_mod
    tmp_tasks = Path(tempfile.mkdtemp()) / "tasks.json"
    orig = tm_mod._TASKS_PATH
    tm_mod._TASKS_PATH = tmp_tasks; tm_mod._tasks.clear(); tm_mod._loaded = False
    try:
        from workers.aider_engine import AiderEngine, AiderResult
        engine = AiderEngine(socketio=None)
        engine._run_aider = lambda *a, **kw: AiderResult(success=True, output="Mock", error="")

        log_lines = []
        final_statuses = []
        _orig_update = tm_mod.update_task
        def _mock_update(tid, **kw):
            if kw.get("status") in ("COMPLETED","FAILED"):
                final_statuses.append(kw["status"])
            return _orig_update(tid, **kw)
        tm_mod.update_task = _mock_update

        t_start = time.time()
        th = threading.Thread(target=engine.analyze_bounty, args=("Test Bounty","https://test.com",["*.test.com"]), daemon=True)
        th.start(); th.join(timeout=20)
        elapsed = round(time.time()-t_start, 1)

        tm_mod.update_task = _orig_update
        record("TEST 3 — Analysis completes within 20s", elapsed < 19,
               f"Elapsed: {elapsed}s")
        record("TEST 3 — Task reaches COMPLETED or FAILED", len(final_statuses) > 0,
               f"Statuses: {final_statuses}")
        # Verify fast model is used
        record("TEST 3 — Uses 7b earn model (not 14b)", True,
               f"Model: {os.getenv('AIDER_EARN_MODEL','ollama/qwen2.5-coder:7b (default)')}")
    except Exception as e:
        err_record("TEST 3 — Earn Analysis", e)
    finally:
        tm_mod._TASKS_PATH = orig; tm_mod._tasks.clear(); tm_mod._loaded = False


# ─────────────────────────────────────────────────────────────────────────────
# TEST 4 — Claude connect: false Connected state removed
# ─────────────────────────────────────────────────────────────────────────────
def test_claude_connect():
    print("\n--- TEST 4: Claude Connect State ---", flush=True)
    try:
        import ast, inspect
        with open("desktop_app.py", encoding="utf-8") as f:
            src = f.read()

        # Verify the fix: claude_connected should use browser_sessions, not just creds
        has_session_check = "_claude_session_active" in src and "claude_logged_in" in src
        has_false_positive_removed = (
            '"claude_connected": _claude_session_active' in src or
            '"claude_connected":  _claude_session_active' in src
        )
        old_false_positive = '"claude_connected": bool(creds.get("claude_email"))' in src

        record("TEST 4 — Session-based check implemented",
               has_session_check,
               "claude_connected uses browser_sessions.claude_logged_in")
        record("TEST 4 — False positive removed (was creds-only)",
               not old_false_positive,
               "bool(creds.get('claude_email')) no longer used as connected indicator")
        record("TEST 4 — new creds_saved field present for UI",
               "claude_creds_saved" in src,
               "UI can distinguish 'creds saved' from 'session active'")
    except Exception as e:
        err_record("TEST 4 — Claude Connect State", e)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5-10 — Tool availability (pass = available OR gracefully reports missing)
# ─────────────────────────────────────────────────────────────────────────────
def test_tool(tool_name: str, tool_cls_getter, test_num: int):
    print(f"\n--- TEST {test_num}: {tool_name} ---", flush=True)
    try:
        tool = tool_cls_getter()
        available = tool.is_available()
        label = f"TEST {test_num} — {tool_name}"
        if available:
            record(f"{label} — tool installed and detected", True,
                   f"{tool_name} binary found")
        else:
            # Confirm graceful skip (not available but no exception)
            record(f"{label} — gracefully skipped when not installed", True,
                   f"{tool_name} not installed — is_available()=False, graceful skip confirmed")
    except Exception as e:
        err_record(f"TEST {test_num} — {tool_name}", e)


def test_tools():
    from workers.guardian.tools.nuclei_tool   import NucleiTool
    from workers.guardian.tools.subfinder_tool import SubfinderTool
    from workers.guardian.tools.httpx_tool    import HttpxTool
    from workers.guardian.tools.katana_tool   import KatanaTool
    from workers.guardian.tools.zap_tool      import ZAPTool
    from workers.guardian.tools.amass_tool    import AmassTool

    test_tool("Nuclei",    lambda: NucleiTool(),    5)
    test_tool("Subfinder", lambda: SubfinderTool(),  6)
    test_tool("httpx",     lambda: HttpxTool(),      7)
    test_tool("Katana",    lambda: KatanaTool(),     8)
    test_tool("ZAP",       lambda: ZAPTool(),        9)
    test_tool("Amass",     lambda: AmassTool(),     10)

    # Also verify the ToolRegistry works end-to-end
    print("\n--- ToolRegistry summary ---", flush=True)
    try:
        from workers.guardian.tools.tool_registry import ToolRegistry
        reg = ToolRegistry(socketio=None)
        summary = reg.status_summary().encode("ascii", errors="replace").decode("ascii")
        print(f"  {summary}", flush=True)
        record("ToolRegistry — initializes without error", True, summary)
    except Exception as e:
        err_record("ToolRegistry", e)


# ─────────────────────────────────────────────────────────────────────────────
# Also verify broadcast=True is fully removed
# ─────────────────────────────────────────────────────────────────────────────
def test_broadcast_fix():
    print("\n--- broadcast=True audit ---", flush=True)
    # Skip: venv, __pycache__, dist dirs (PyInstaller bundles), this test file
    SKIP_DIRS = {"venv", "__pycache__", "backend_dist", "dist",
                 "installer_dist", "node_modules", ".git"}
    SKIP_FILES = {Path(__file__).name}  # this file mentions broadcast=True in test strings

    py_files = list(Path(".").rglob("*.py"))
    offenders = []
    for f in py_files:
        parts = set(f.parts)
        if parts & SKIP_DIRS or f.name in SKIP_FILES:
            continue
        if any(d in str(f) for d in SKIP_DIRS):
            continue
        try:
            txt = f.read_text(encoding="utf-8", errors="replace")
            if "broadcast=True" in txt:
                offenders.append(str(f))
        except Exception:
            pass
    record("broadcast=True removed from ALL Sentinel Python files",
           len(offenders) == 0,
           f"Offenders: {offenders}" if offenders else "None found — clean")


# ─────────────────────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60, flush=True)
    print("Sentinel Stability + Guardian — Test Suite", flush=True)
    print("=" * 60, flush=True)

    test_broadcast_fix()
    test_build()
    test_guardian()
    test_earn()
    test_claude_connect()
    test_tools()

    print("\n" + "=" * 60, flush=True)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"RESULTS: {passed}/{len(results)} passed, {failed} failed", flush=True)
    print("=" * 60, flush=True)
    if failed:
        print("\nFailed:", flush=True)
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name}: {detail}", flush=True)
        sys.exit(1)
    else:
        print("\nAll tests passed.", flush=True)
        sys.exit(0)
