"""
run_odysseus_tests.py — Sentinel Odysseus Enhancement Tests
Tests:
  1  Guardian scan  => task appears, progress updates, final report
  2  Earn analysis  => task appears, progress updates, completion/failure
  3  Build task     => task created, artifact created
  4  Launch         => launch button works (artifact registry)
  5  Project assign => task assigned to project
  6  Restart app    => tasks and artifacts persist
"""
import os
import sys
import time
import uuid
import json
import shutil
import threading
import tempfile
import traceback
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

PASSED  = "[PASS]"
FAILED  = "[FAIL]"
ERRORED = "[ERR] "

results = []

def result(name, ok, detail=""):
    sym = PASSED if ok else FAILED
    print(f"{sym} {name}", flush=True)
    if detail:
        print(f"       {detail}", flush=True)
    results.append((name, ok, detail))

def err_result(name, exc):
    print(f"{ERRORED} {name}: {exc}", flush=True)
    traceback.print_exc()
    results.append((name, False, str(exc)))


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def isolated_task_manager():
    """Return a fresh task_manager module backed by a temp directory."""
    import importlib, types
    # patch _TASKS_PATH to a temp file
    import workers.task_manager as tm
    tmp = Path(tempfile.mkdtemp()) / "tasks.json"
    original_path = tm._TASKS_PATH
    tm._TASKS_PATH = tmp
    tm._tasks.clear()
    tm._loaded = False
    return tm, original_path, tmp


def restore_task_manager(tm, original_path):
    tm._TASKS_PATH = original_path
    tm._tasks.clear()
    tm._loaded = False


def isolated_artifact_registry():
    from workers.artifacts import artifact_registry as ar
    tmp = Path(tempfile.mkdtemp()) / "registry.json"
    original = ar._REGISTRY_PATH
    ar._REGISTRY_PATH = tmp
    ar._registry.clear()
    ar._loaded = False
    return ar, original, tmp


def restore_artifact_registry(ar, original):
    ar._REGISTRY_PATH = original
    ar._registry.clear()
    ar._loaded = False


def isolated_project_manager():
    from workers.projects import project_manager as pm
    tmp = Path(tempfile.mkdtemp()) / "projects.json"
    original = pm._PROJECTS_PATH
    pm._PROJECTS_PATH = tmp
    pm._projects.clear()
    pm._loaded = False
    return pm, original


def restore_project_manager(pm, original):
    pm._PROJECTS_PATH = original
    pm._projects.clear()
    pm._loaded = False


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1 — Guardian task tracking
# ─────────────────────────────────────────────────────────────────────────────

def test_guardian():
    print("\n--- TEST 1: Guardian Task Tracking ---", flush=True)
    tm, orig_path, tmp = isolated_task_manager()

    try:
        from workers.guardian.guardian_brain import GuardianBrain

        brain = GuardianBrain(socketio=None)

        # Track what tasks were created / updated
        created_tasks  = []
        progress_seen  = []
        completed_seen = []

        _orig_create = tm.create_task
        _orig_update = tm.update_task

        def _mock_create(title, source="system", **kw):
            t = _orig_create(title, source=source, **kw)
            created_tasks.append(t)
            return t

        def _mock_update(task_id, **kw):
            t = _orig_update(task_id, **kw)
            if t:
                if kw.get("progress") is not None:
                    progress_seen.append(kw["progress"])
                if kw.get("status") == "COMPLETED":
                    completed_seen.append(task_id)
            return t

        tm.create_task = _mock_create
        tm.update_task = _mock_update

        # Mock Ollama so AI stage finishes instantly
        brain._call_ollama = lambda *a, **kw: "Mocked AI analysis result."

        # Run the assessment
        brain._run_full_assessment("example.com")
        time.sleep(5)   # give the background thread time to complete

        tm.create_task = _orig_create
        tm.update_task = _orig_update

        task_appeared  = len(created_tasks) > 0
        progress_updated = len(progress_seen) > 0
        final_complete = len(completed_seen) > 0

        result("TEST 1 – Task appears for Guardian scan", task_appeared,
               f"Created tasks: {[t['title'] for t in created_tasks]}")
        result("TEST 1 – Progress updates during scan", progress_updated,
               f"Progress values seen: {sorted(set(progress_seen))}")
        result("TEST 1 – Task marked COMPLETED at end", final_complete,
               f"Completed task IDs: {completed_seen}")

    except Exception as e:
        err_result("TEST 1 – Guardian task tracking", e)
    finally:
        restore_task_manager(tm, orig_path)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2 — Earn task tracking
# ─────────────────────────────────────────────────────────────────────────────

def test_earn():
    print("\n--- TEST 2: Earn Task Tracking ---", flush=True)
    tm, orig_path, tmp = isolated_task_manager()

    try:
        from workers.aider_engine import AiderEngine, AiderResult

        engine = AiderEngine(socketio=None)

        created_tasks  = []
        progress_seen  = []
        final_statuses = []

        _orig_create = tm.create_task
        _orig_update = tm.update_task

        def _mock_create(title, source="system", **kw):
            t = _orig_create(title, source=source, **kw)
            created_tasks.append(t)
            return t

        def _mock_update(task_id, **kw):
            t = _orig_update(task_id, **kw)
            if t:
                if kw.get("progress") is not None:
                    progress_seen.append(kw["progress"])
                if kw.get("status") in ("COMPLETED", "FAILED"):
                    final_statuses.append(kw["status"])
            return t

        tm.create_task = _mock_create
        tm.update_task = _mock_update

        # Mock _run_aider so it doesn't actually run Aider
        engine._run_aider = lambda *a, **kw: AiderResult(
            success=True,
            output="Mocked bounty analysis complete.",
            error=""
        )

        th = threading.Thread(
            target=engine.analyze_bounty,
            args=("Coupang Taiwan", "https://hackerone.com/coupang", ["*.coupang.com"]),
            daemon=True,
        )
        th.start()
        th.join(timeout=20)

        tm.create_task = _orig_create
        tm.update_task = _orig_update

        result("TEST 2 – Task appears for Earn analysis",
               len(created_tasks) > 0,
               f"Created: {[t['title'] for t in created_tasks]}")
        result("TEST 2 – Progress updates during analysis",
               len(progress_seen) > 0,
               f"Progress values: {sorted(set(progress_seen))}")
        result("TEST 2 – Task reaches COMPLETED or FAILED",
               len(final_statuses) > 0,
               f"Final statuses: {final_statuses}")

    except Exception as e:
        err_result("TEST 2 – Earn task tracking", e)
    finally:
        restore_task_manager(tm, orig_path)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3 — Build task + artifact
# ─────────────────────────────────────────────────────────────────────────────

def test_build_task_and_artifact():
    print("\n--- TEST 3: Build Task + Artifact ---", flush=True)

    # Use isolated stores
    tm, tm_orig, _ = isolated_task_manager()
    ar, ar_orig, _ = isolated_artifact_registry()

    try:
        # Simulate what _run_approved_build does (without importing desktop_app)
        tmp_dir  = Path(tempfile.mkdtemp())
        entry    = tmp_dir / "main.py"
        entry.write_text("print('Calculator')\n")

        task_ids_created = []
        artifact_ids_created = []

        # Mock socket emit
        class _FakeSio:
            def emit(self, *a, **kw): pass

        sio = _FakeSio()

        from workers.task_manager import TaskContext, COMPLETED
        from workers.artifacts.artifact_registry import register_artifact

        # Simulate the build wrapper
        def _simulated_build(desc, odir):
            with TaskContext(f"Build {desc}", source="forge") as ctx:
                task_ids_created.append(ctx.task_id)
                ctx.progress(10, "Planning")
                ctx.progress(30, "Building")
                # Simulate a successful build result
                ctx.progress(85, "Verifying")
                art = register_artifact(
                    task=desc,
                    entry_point=str(entry),
                    output_dir=str(tmp_dir),
                    files=[str(entry)],
                    task_id=ctx.task_id,
                )
                artifact_ids_created.append(art["id"])
                ctx.complete(
                    result_summary=f"Built {desc}",
                    artifact_id=art["id"]
                )

        _simulated_build("Calculator", str(tmp_dir))

        result("TEST 3 – Task created for build",
               len(task_ids_created) > 0,
               f"Task IDs: {task_ids_created}")
        result("TEST 3 – Artifact registered after build",
               len(artifact_ids_created) > 0,
               f"Artifact IDs: {artifact_ids_created}")

        # Verify the task is COMPLETED
        task = tm.get_task(task_ids_created[0])
        result("TEST 3 – Build task status is COMPLETED",
               task and task["status"] == "COMPLETED",
               f"Status: {task.get('status') if task else 'NOT FOUND'}")

        # Verify artifact data
        art_rec = ar.get_artifact(artifact_ids_created[0])
        result("TEST 3 – Artifact entry_point stored",
               art_rec and bool(art_rec.get("entry_point")),
               f"Entry: {art_rec.get('entry_point') if art_rec else 'NONE'}")

        shutil.rmtree(tmp_dir, ignore_errors=True)

    except Exception as e:
        err_result("TEST 3 – Build task + artifact", e)
    finally:
        restore_task_manager(tm, tm_orig)
        restore_artifact_registry(ar, ar_orig)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 4 — Launch artifact
# ─────────────────────────────────────────────────────────────────────────────

def test_launch_artifact():
    print("\n--- TEST 4: Launch Artifact ---", flush=True)
    ar, ar_orig, _ = isolated_artifact_registry()

    try:
        tmp_dir = Path(tempfile.mkdtemp())
        entry   = tmp_dir / "hello.py"
        entry.write_text("print('Hello from Calculator')\n")

        from workers.artifacts.artifact_registry import register_artifact, get_latest_artifact, launch_artifact

        art = register_artifact(
            task="Calculator",
            entry_point=str(entry),
            output_dir=str(tmp_dir),
            files=[str(entry)],
        )

        result("TEST 4 – Artifact registered",
               art and bool(art.get("id")),
               f"ID: {art.get('id')}")
        result("TEST 4 – Launch command derived",
               bool(art.get("launch_command")),
               f"Cmd: {art.get('launch_command')}")

        latest = get_latest_artifact()
        result("TEST 4 – get_latest_artifact returns artifact",
               latest and latest["id"] == art["id"],
               f"Latest ID: {latest['id'] if latest else 'NONE'}")

        # Test launch (we check it doesn't raise — don't actually open a window)
        launch_res = launch_artifact(art)
        result("TEST 4 – launch_artifact returns ok=True",
               launch_res.get("ok") is True,
               f"Result: {launch_res}")

        shutil.rmtree(tmp_dir, ignore_errors=True)

    except Exception as e:
        err_result("TEST 4 – Launch artifact", e)
    finally:
        restore_artifact_registry(ar, ar_orig)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5 — Project assignment
# ─────────────────────────────────────────────────────────────────────────────

def test_project_assignment():
    print("\n--- TEST 5: Project Assignment ---", flush=True)
    tm, tm_orig, _ = isolated_task_manager()
    pm, pm_orig    = isolated_project_manager()

    try:
        from workers.projects.project_manager import create_project, get_project
        from workers.task_manager import create_task, update_task, get_task

        # Create project
        proj = create_project("Sentinel Prime", color="#00ff88")
        result("TEST 5 – Project created",
               bool(proj.get("id")),
               f"ID: {proj['id']}, Name: {proj['name']}")

        # Create task and assign project
        task = create_task("Guardian Scan — sentinelprime.org", source="guardian",
                           project_id=proj["id"])
        result("TEST 5 – Task created with project_id",
               task.get("project_id") == proj["id"],
               f"Task project_id: {task.get('project_id')}")

        # Update task to link to project (simulate mid-flight assignment)
        update_task(task["id"], metadata_update={"extra": "demo"})
        refreshed = get_task(task["id"])
        result("TEST 5 – Task project persists after update",
               refreshed and refreshed.get("project_id") == proj["id"],
               f"project_id: {refreshed.get('project_id') if refreshed else 'NONE'}")

        # Verify project retrieval
        p2 = get_project(proj["id"])
        result("TEST 5 – Project retrievable by ID",
               p2 and p2["name"] == "Sentinel Prime",
               f"Name: {p2['name'] if p2 else 'NOT FOUND'}")

    except Exception as e:
        err_result("TEST 5 – Project assignment", e)
    finally:
        restore_task_manager(tm, tm_orig)
        restore_project_manager(pm, pm_orig)


# ─────────────────────────────────────────────────────────────────────────────
# TEST 6 — Persistence (tasks + artifacts survive reload)
# ─────────────────────────────────────────────────────────────────────────────

def test_persistence():
    print("\n--- TEST 6: Persistence (restart simulation) ---", flush=True)

    import workers.task_manager as tm_mod
    import workers.artifacts.artifact_registry as ar_mod

    tmp_task = Path(tempfile.mkdtemp()) / "tasks.json"
    tmp_art  = Path(tempfile.mkdtemp()) / "registry.json"

    orig_tm_path = tm_mod._TASKS_PATH
    orig_ar_path = ar_mod._REGISTRY_PATH

    try:
        # --- Write phase ---
        tm_mod._TASKS_PATH = tmp_task
        tm_mod._tasks.clear();  tm_mod._loaded = False

        ar_mod._REGISTRY_PATH = tmp_art
        ar_mod._registry.clear(); ar_mod._loaded = False

        from workers.task_manager import create_task
        from workers.artifacts.artifact_registry import register_artifact

        tmp_dir = Path(tempfile.mkdtemp())
        entry   = tmp_dir / "app.py"
        entry.write_text("print('app')\n")

        t = create_task("Build Persistence Test", source="forge")
        a = register_artifact("PersistApp", entry_point=str(entry), output_dir=str(tmp_dir))

        # --- Simulate restart: clear in-memory caches ---
        tm_mod._tasks.clear();    tm_mod._loaded = False
        ar_mod._registry.clear(); ar_mod._loaded = False

        # --- Read phase (reload from disk) ---
        from workers.task_manager import get_task, list_tasks
        from workers.artifacts.artifact_registry import get_latest_artifact

        t2 = get_task(t["id"])
        a2 = get_latest_artifact()

        result("TEST 6 – Task persists after simulated restart",
               t2 is not None and t2["id"] == t["id"],
               f"Loaded title: {t2.get('title') if t2 else 'NOT FOUND'}")
        result("TEST 6 – Artifact persists after simulated restart",
               a2 is not None and a2["id"] == a["id"],
               f"Loaded task: {a2.get('task') if a2 else 'NOT FOUND'}")

        shutil.rmtree(tmp_dir, ignore_errors=True)

    except Exception as e:
        err_result("TEST 6 – Persistence", e)
    finally:
        tm_mod._TASKS_PATH = orig_tm_path
        tm_mod._tasks.clear();  tm_mod._loaded = False
        ar_mod._REGISTRY_PATH = orig_ar_path
        ar_mod._registry.clear(); ar_mod._loaded = False


# ─────────────────────────────────────────────────────────────────────────────
# Run all tests
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Sentinel Odysseus Enhancement — Test Suite")
    print("=" * 60)

    test_guardian()
    test_earn()
    test_build_task_and_artifact()
    test_launch_artifact()
    test_project_assignment()
    test_persistence()

    print("\n" + "=" * 60)
    passed  = sum(1 for _, ok, _ in results if ok)
    failed  = sum(1 for _, ok, _ in results if not ok)
    total   = len(results)
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    print("=" * 60)

    if failed:
        print("\nFailed tests:")
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name}: {detail}")
        sys.exit(1)
    else:
        print("\nAll tests passed.")
        sys.exit(0)
