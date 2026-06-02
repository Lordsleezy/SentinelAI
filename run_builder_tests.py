"""
run_builder_tests.py — Builder Ecosystem validation (no npm/godot required for scaffolds).
"""
import os
import sys
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

results = []


def record(name: str, ok: bool, detail: str = "") -> None:
    sym = "[PASS]" if ok else "[FAIL]"
    print(f"{sym} {name}")
    if detail:
        print(f"       {detail}")
    results.append((name, ok, detail))


def test_router():
    from builders.router import classify_build, BuildType
    record("Router Flappy Bird -> GAME", classify_build("Build Flappy Bird") == BuildType.GAME)
    record("Router calculator -> DESKTOP", classify_build("Build a calculator") == BuildType.DESKTOP)
    record("Router website -> WEB", classify_build("Build company website") == BuildType.WEB)
    record("Router Android -> ANDROID", classify_build("Build Android budgeting app") == BuildType.ANDROID)
    record("Router script -> PYTHON", classify_build("Build a Python CLI script") == BuildType.PYTHON)


def _build_in_tmp(fn, desc: str):
    tmp = Path(tempfile.mkdtemp(prefix="sentinel_build_"))
    try:
        return fn(desc, str(tmp)), tmp
    except Exception as e:
        shutil.rmtree(tmp, ignore_errors=True)
        raise e


def test_calculator():
    from builders.forge_engine import ForgeBuildEngine
    from builders.router import BuildType, classify_build
    assert classify_build("Build calculator") == BuildType.DESKTOP
    tmp = Path(tempfile.mkdtemp())
    try:
        r = ForgeBuildEngine(None).build("Build calculator", str(tmp))
        ok = r.project_type == "DESKTOP" and (tmp / "package.json").exists() and (tmp / "main.js").exists()
        record("TEST 1 - Calculator -> Desktop/Electron", ok, f"builder={r.builder} verified={r.verified}")
        record("TEST 1 - Launch command set", bool(r.launch_command), r.launch_command[:80])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_flappy():
    from builders.forge_engine import ForgeBuildEngine
    tmp = Path(tempfile.mkdtemp())
    try:
        r = ForgeBuildEngine(None).build("Build Flappy Bird", str(tmp))
        godot = (tmp / "project.godot").exists()
        record("TEST 2 - Flappy Bird -> Godot project", godot and r.project_type == "GAME", f"builder={r.builder}")
        record("TEST 2 - Not Tkinter-only", not (tmp / "main.py").exists())
        record("TEST 2 - Launch command", bool(r.launch_command), r.launch_command[:80])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_website():
    from builders.forge_engine import ForgeBuildEngine
    tmp = Path(tempfile.mkdtemp())
    try:
        r = ForgeBuildEngine(None).build("Build landscaping website", str(tmp))
        ok = (tmp / "package.json").exists() and (tmp / "app" / "page.tsx").exists()
        record("TEST 3 - Website -> Next.js", ok, f"builder={r.builder}")
        record("TEST 3 - npm dev launch", "npm" in (r.launch_command or ""))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_android():
    from builders.forge_engine import ForgeBuildEngine
    tmp = Path(tempfile.mkdtemp())
    try:
        r = ForgeBuildEngine(None).build("Build Android budgeting app", str(tmp))
        gradle = (tmp / "app" / "build.gradle.kts").exists()
        record("TEST 4 - Android -> Compose scaffold", gradle and r.project_type == "ANDROID", r.builder)
        record("TEST 4 - Gradle launch hint", "gradle" in (r.launch_command or "").lower())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_launch_and_artifact():
    import workers.artifacts.artifact_registry as ar
    tmp_reg = Path(tempfile.mkdtemp()) / "reg.json"
    orig = ar._REGISTRY_PATH
    ar._REGISTRY_PATH = tmp_reg
    ar._registry.clear()
    ar._loaded = False
    try:
        from workers.artifacts.artifact_registry import register_artifact, get_latest_artifact, launch_artifact
        art = register_artifact(
            "Test Calc", entry_point="", output_dir=str(Path(tempfile.mkdtemp())),
            launch_command='echo sentinel_launch_test',
            builder_used="Electron", project_type="DESKTOP", verification_status="verified",
        )
        latest = get_latest_artifact()
        record("TEST 5 - Latest artifact", latest and latest["id"] == art["id"])
        record("TEST 5 - Builder metadata", art.get("builder_used") == "Electron")
        record("TEST 5 - Launch command stored", "sentinel_launch" in art.get("launch_command", ""))
    finally:
        ar._REGISTRY_PATH = orig
        ar._registry.clear()
        ar._loaded = False


def test_verification_detects_missing():
    from builders.common.types import BuildResult, VerificationResult
    from builders.common.verify import verify_build
    from builders.router import BuildType
    br = BuildResult(success=True, builder="Test", project_type="GAME", output_dir=str(Path(tempfile.mkdtemp())))
    v = verify_build(br, BuildType.GAME, None)
    record("TEST 6 - Broken Godot detected", not v.verified, v.message)


if __name__ == "__main__":
    print("=" * 60)
    print("Sentinel Builder Ecosystem Tests")
    print("=" * 60)
    test_router()
    test_calculator()
    test_flappy()
    test_website()
    test_android()
    test_launch_and_artifact()
    test_verification_detects_missing()
    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    print("=" * 60)
    print(f"RESULTS: {passed}/{len(results)} passed, {failed} failed")
    sys.exit(1 if failed else 0)
