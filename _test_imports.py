"""Quick import and unit test — run with: python _test_imports.py"""
import sys, json

# ─── db.py ───────────────────────────────────────────────────────────────────
import db
db.init_db()
opp_id = db.insert_opportunity(
    "test", "Fix typo in README", "https://github.com/x/y",
    "https://github.com/x/y/issues/1", 100, "USD", 2.0
)
print(f"db.py:            OK  (inserted opp_id={opp_id})")
db.log_event("test_event", "test detail", opp_id)
logs = db.get_recent_logs(5)
assert len(logs) >= 1
summary = db.get_earnings_summary()
print(f"  earnings summary: {summary}")

# ─── scanner helpers ─────────────────────────────────────────────────────────
from scanner import score_opportunity, estimate_complexity, _parse_amount, _extract_bounty_from_text
s = score_opportunity(150, 2, 3, 500, 5, "python")
assert 0 < s <= 10, f"bad score: {s}"
cx = estimate_complexity("fix typo in docs", "small documentation fix", 0)
assert 1 <= cx <= 5, f"bad complexity: {cx}"
amt = _parse_amount("$1.5K")
assert amt == 1500, f"bad amount: {amt}"
bt = _extract_bounty_from_text("Reward: $250 for fixing this bug")
assert bt == 250, f"bad bounty text: {bt}"
print(f"scanner.py:       OK  (score={s}, complexity={cx}, amount=${amt}, bounty_text=${bt})")

# ─── prompt_engine ────────────────────────────────────────────────────────────
from prompt_engine import (
    compress_context, parse_and_validate_response,
    build_fix_prompt, build_verification_prompt, build_retry_prompt,
    build_complexity_assessment_prompt, ROLE_PRIMER, LANG_RULES, _extract_keywords
)

# Context compression
files = {
    "main.py":  ("def foo():\n    pass\n" * 200),
    "utils.py": ("import os\ndef helper(): return 1\n"),
}
ctx = compress_context(files, ["foo", "helper"])
assert len(ctx) > 50
print(f"  compress_context: {len(ctx)} chars from 2 files")

# JSON parsing — plain
good = json.dumps({
    "confidence": 8,
    "fix": {"files": []},
    "diagnosis": "test",
    "explanation": "x",
    "chain_of_thought": {}
})
r = parse_and_validate_response(good)
assert r is not None and r["confidence"] == 8
print(f"  parse plain JSON: confidence={r['confidence']}")

# JSON parsing — wrapped in markdown fence
fenced = "```json\n" + good + "\n```"
r2 = parse_and_validate_response(fenced)
assert r2 is not None and r2["confidence"] == 8
print(f"  parse fenced JSON: confidence={r2['confidence']}")

# JSON parsing — with prose wrapping
wrapped = "Sure, here is the result:\n" + good + "\nLet me know if you need changes."
r3 = parse_and_validate_response(wrapped)
assert r3 is not None and r3["confidence"] == 8
print(f"  parse wrapped JSON: confidence={r3['confidence']}")

# Keyword extraction
kws = _extract_keywords("Fix the NullPointerException in UserService.authenticate when token is None")
assert "NullPointerException" in kws or "UserService" in kws
print(f"  keywords: {kws[:5]}")

# Prompt building
issue = {"title": "Fix null error", "body": "Crashes on None input", "issue_url": "https://github.com/x/y/issues/1", "comments": []}
fix_p  = build_fix_prompt(issue, ctx, "python")
ver_p  = build_verification_prompt(issue, r)
retry_p = build_retry_prompt(issue, "failed attempt", "confidence 4/10")
cx_p   = build_complexity_assessment_prompt("Fix typo", "Minor docs fix")
assert "Chain of Thought" in fix_p
assert "Critical Review" in ver_p
assert "previous analysis was too complex" in retry_p
assert "complexity" in cx_p.lower()
print(f"  build_fix_prompt:   {len(fix_p)} chars")
print(f"  build_verify_prompt:{len(ver_p)} chars")
print(f"  build_retry_prompt: {len(retry_p)} chars")
print(f"  build_cx_prompt:    {len(cx_p)} chars")
print(f"prompt_engine.py: OK")

# ─── executor helpers ────────────────────────────────────────────────────────
from executor import _build_pr_body, read_repo_files, apply_fixes_atomic
import tempfile, pathlib

# Test apply_fixes_atomic with rollback
with tempfile.TemporaryDirectory() as tmpdir:
    td = pathlib.Path(tmpdir)
    (td / "foo.py").write_text("x = 1\ny = 2\n")
    fix_data = {
        "fix": {"files": [{"path": "foo.py", "action": "modify",
                            "changes": [{"description": "fix x", "old_code": "x = 1", "new_code": "x = 99"}]}]}
    }
    ok, modified = apply_fixes_atomic(td, fix_data)
    assert ok and "foo.py" in modified
    content = (td / "foo.py").read_text()
    assert "x = 99" in content
    print(f"executor.py:      OK  (atomic apply: modified={modified})")

    # Test rollback on bad old_code
    bad_fix = {
        "fix": {"files": [{"path": "foo.py", "action": "modify",
                            "changes": [{"description": "bad", "old_code": "THIS_DOES_NOT_EXIST", "new_code": "z=0"}]}]}
    }
    ok2, _ = apply_fixes_atomic(td, bad_fix)
    assert not ok2
    # Verify rollback restored original state (x = 99 still there from previous good apply)
    content2 = (td / "foo.py").read_text()
    assert "x = 99" in content2  # unchanged — rollback worked
    print(f"  rollback on bad old_code: OK")

# ─── monitor helpers ─────────────────────────────────────────────────────────
from monitor import _parse_pr_url, run_monitor
owner, repo, num = _parse_pr_url("https://github.com/facebook/react/pull/123")
assert owner == "facebook" and repo == "react" and num == "123"
owner2, repo2, num2 = _parse_pr_url("https://github.com/x/y/pull/DRYRUN")
assert owner2 is None
print(f"monitor.py:       OK  (parse PR URL: {owner}/{repo}#{num})")

# ─── dashboard import ────────────────────────────────────────────────────────
from dashboard import app
assert app.title == "Sentinel Earn"
print(f"dashboard.py:     OK  (FastAPI app title='{app.title}')")

print()
print("=" * 52)
print("  ALL IMPORTS AND UNIT TESTS PASSED -- OK")
print("=" * 52)
