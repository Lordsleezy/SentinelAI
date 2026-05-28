"""
repair_intelligence.py — Higher-order reasoning helpers for the repair pipeline.

This module isolates the "make it think more like Claude" layer from raw
prompt construction. Every helper is designed to fail silently — if a helper
errors out, the core repair pipeline continues unaffected.

Contents:
  * extract_issue_signals      — stack traces, file refs, error strings from issue body
  * detect_repo_conventions    — quick style/convention scan
  * validate_proposed_patch    — pre-flight old_code/syntax check
  * build_patch_repair_prompt  — auto-correction prompt for invalid patches
  * chain_of_verification      — CoVe — independent Q&A on the proposed fix
  * remember_failed_repair     — persist anti-examples to PersistentMemory
  * retrieve_similar_past_failures — recall anti-examples for new attempts
  * resolve_symbols            — locate definitions of mentioned identifiers
  * analyze_caller_impact      — find callers of symbols touched by the fix
  * verify_code_grounding      — check the diagnosis quotes real code
  * detect_test_coverage       — locate tests covering the modified files
  * score_diff_minimality      — measure how minimal the proposed change is
  * classify_issue_intent_local — heuristic bug/feature/question classifier
  * ReasoningTrace             — pipeline-wide decision log
"""
from __future__ import annotations

import ast
import json
import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─── 1. Structured issue signal extraction ───────────────────────────────────

_PY_TRACE_RE = re.compile(
    r'File "([^"]+)", line (\d+), in (\S+)\n\s+(.+)',
    re.MULTILINE,
)
_JS_TRACE_RE = re.compile(
    r"at\s+(\S+)\s*\(([^)]+):(\d+):(\d+)\)",
    re.MULTILINE,
)
_FILE_LINE_RE = re.compile(
    r"(?:^|\s)([a-zA-Z0-9_/.\-]+\.(?:py|js|ts|tsx|jsx|java|go|rs|rb)):(\d+)",
)
_ERROR_QUOTE_RE = re.compile(r"`([^`\n]{6,120})`")
_ERROR_LINE_RE = re.compile(
    r"^\s*([A-Z][a-zA-Z]+(?:Error|Exception|Warning))\s*:\s*(.+)$",
    re.MULTILINE,
)
_IDENT_RE = re.compile(r"\b([A-Z][a-zA-Z0-9_]+|[a-z_][a-zA-Z0-9_]*\.[a-zA-Z_][a-zA-Z0-9_]*)\b")


def extract_issue_signals(title: str, body: str) -> Dict[str, List]:
    """Pull structured signals out of free-text issue title/body."""
    text = f"{title}\n{body or ''}"
    signals: Dict[str, List] = {
        "stack_frames": [],
        "file_refs": [],
        "errors": [],
        "code_quotes": [],
        "identifiers": [],
    }

    try:
        for m in _PY_TRACE_RE.finditer(text):
            signals["stack_frames"].append({
                "file": m.group(1), "line": int(m.group(2)),
                "function": m.group(3), "code": m.group(4).strip(),
                "lang": "python",
            })
        for m in _JS_TRACE_RE.finditer(text):
            signals["stack_frames"].append({
                "file": m.group(2), "line": int(m.group(3)),
                "function": m.group(1), "code": "",
                "lang": "javascript",
            })
        for m in _FILE_LINE_RE.finditer(text):
            ref = {"file": m.group(1), "line": int(m.group(2))}
            if ref not in signals["file_refs"]:
                signals["file_refs"].append(ref)
        for m in _ERROR_LINE_RE.finditer(text):
            signals["errors"].append({"type": m.group(1), "message": m.group(2).strip()[:240]})
        for m in _ERROR_QUOTE_RE.finditer(text):
            q = m.group(1).strip()
            if q and q not in signals["code_quotes"]:
                signals["code_quotes"].append(q[:160])
                if len(signals["code_quotes"]) >= 8:
                    break
        # Dotted identifiers (e.g., foo.bar) are high-value
        for m in _IDENT_RE.finditer(text):
            ident = m.group(1)
            if "." in ident and ident not in signals["identifiers"]:
                signals["identifiers"].append(ident)
                if len(signals["identifiers"]) >= 10:
                    break
    except Exception as exc:
        logger.debug("[signals] extraction non-fatal: %s", exc)

    return signals


def format_signals_for_prompt(signals: Dict[str, List]) -> str:
    parts: List[str] = []
    if signals.get("stack_frames"):
        lines = [
            f"- {f['file']}:{f['line']} in {f['function']}() — `{f['code']}`"
            for f in signals["stack_frames"][:5]
        ]
        parts.append("**Stack frames from issue:**\n" + "\n".join(lines))
    if signals.get("errors"):
        lines = [f"- {e['type']}: {e['message']}" for e in signals["errors"][:3]]
        parts.append("**Error messages:**\n" + "\n".join(lines))
    if signals.get("file_refs"):
        lines = [f"- {r['file']}:{r['line']}" for r in signals["file_refs"][:5]]
        parts.append("**File references in issue:**\n" + "\n".join(lines))
    if signals.get("code_quotes"):
        lines = [f"- `{q}`" for q in signals["code_quotes"][:5]]
        parts.append("**Code snippets quoted in issue:**\n" + "\n".join(lines))
    if signals.get("identifiers"):
        parts.append("**Identifiers mentioned:** " + ", ".join(signals["identifiers"][:8]))

    if not parts:
        return ""
    return "## Extracted Signals (parsed from issue text)\n" + "\n\n".join(parts) + "\n"


def signal_files_to_prioritize(signals: Dict[str, List]) -> List[str]:
    """Files the issue explicitly references — context retrieval should weight these."""
    refs = set()
    for f in signals.get("stack_frames", []):
        refs.add(f.get("file", ""))
    for r in signals.get("file_refs", []):
        refs.add(r.get("file", ""))
    return [r for r in refs if r]


# ─── 2. Repo convention detection ────────────────────────────────────────────

def detect_repo_conventions(files: Dict[str, str], language: str) -> Dict[str, object]:
    """
    Lightweight style/convention scan. Counts patterns across loaded files
    and emits guidance for the system prompt.
    """
    conventions: Dict[str, object] = {
        "language": language,
        "rules": [],
    }
    if not files:
        return conventions

    try:
        sample = "\n".join(list(files.values())[:10])[:60000]
        lang = language.lower()

        if lang == "python":
            fstr = len(re.findall(r'f"[^"]*\{', sample)) + len(re.findall(r"f'[^']*\{", sample))
            pct = len(re.findall(r'"\s*%\s*\(', sample)) + len(re.findall(r"'\s*%\s*\(", sample))
            fmt = len(re.findall(r'\.format\(', sample))
            if fstr > (pct + fmt):
                conventions["rules"].append("Use f-strings (repo convention).")

            type_hints = len(re.findall(r"def\s+\w+\([^)]*:\s*\w", sample))
            def_total = len(re.findall(r"def\s+\w+\(", sample))
            if def_total >= 2 and type_hints / def_total > 0.5:
                conventions["rules"].append("Use type hints — most functions here are typed.")

            if "import pytest" in sample or "from pytest" in sample:
                conventions["rules"].append("Tests use pytest.")
            elif "import unittest" in sample:
                conventions["rules"].append("Tests use unittest.")

            if re.search(r'"""\s*\n', sample):
                conventions["rules"].append("Functions/classes use triple-quoted docstrings.")

        elif lang in ("javascript", "typescript"):
            arrow = len(re.findall(r"=>\s*[\{(]", sample))
            funcs = len(re.findall(r"\bfunction\s+\w+\(", sample))
            if arrow > funcs * 2:
                conventions["rules"].append("Prefer arrow functions over `function` declarations.")

            if "const " in sample and " var " not in sample:
                conventions["rules"].append("Use const/let — never var.")

            if "describe(" in sample and "it(" in sample:
                conventions["rules"].append("Tests use Jest/Mocha-style describe/it blocks.")
            elif "test(" in sample:
                conventions["rules"].append("Tests use test() blocks (Jest-style).")

            if lang == "typescript":
                interfaces = len(re.findall(r"\binterface\s+\w+", sample))
                types = len(re.findall(r"\btype\s+\w+\s*=", sample))
                if interfaces > 0 or types > 0:
                    conventions["rules"].append(
                        "Define explicit interfaces/types for object shapes."
                    )
    except Exception as exc:
        logger.debug("[conventions] detection non-fatal: %s", exc)

    return conventions


def format_conventions_for_prompt(conventions: Dict[str, object]) -> str:
    rules = conventions.get("rules") or []
    if not rules:
        return ""
    lines = ["## Repo-specific conventions (detected from the code itself)"]
    for r in rules:
        lines.append(f"- {r}")
    return "\n".join(lines) + "\n"


# ─── 3. Pre-flight patch validation ──────────────────────────────────────────

def _normalize_for_match(s: str) -> str:
    """Loose equality — collapse internal whitespace, strip line endings."""
    return re.sub(r"\s+", " ", s).strip()


def validate_proposed_patch(
    fix_result: Dict,
    files: Dict[str, str],
    language: str,
) -> Tuple[bool, List[str]]:
    """
    Verify the proposed patch can plausibly be applied:
      * Every modify-action change's `old_code` actually appears in the target file.
      * After applying all changes in-memory, the resulting Python file still parses.
      * Paths referenced in 'modify' actions exist in the provided files map.

    Returns (is_valid, list_of_errors).
    """
    errors: List[str] = []

    try:
        fix = fix_result.get("fix") or {}
        file_changes = fix.get("files") or []
        if not file_changes:
            return False, ["No file changes in fix"]

        for file_entry in file_changes:
            path = (file_entry.get("path") or "").strip()
            action = (file_entry.get("action") or "modify").lower()
            changes = file_entry.get("changes") or []

            if not path:
                errors.append("File entry missing 'path'")
                continue
            if action != "modify":
                continue

            source = files.get(path)
            if source is None:
                base = path.split("/")[-1]
                matches = [k for k in files if k.endswith(base)]
                if not matches:
                    errors.append(f"File '{path}' not present in loaded context")
                    continue
                source = files[matches[0]]

            # Step A: every old_code must appear (verbatim or whitespace-normalised).
            source_norm = _normalize_for_match(source)
            for i, ch in enumerate(changes):
                old = ch.get("old_code") or ""
                new = ch.get("new_code") or ""
                if not old and not new:
                    errors.append(f"{path}: change #{i+1} is empty")
                    continue
                if old and old not in source and _normalize_for_match(old) not in source_norm:
                    preview = old[:80].replace("\n", "⏎")
                    errors.append(f"{path}: old_code not found in source — `{preview}…`")

            # Step B: apply patches in-memory; AST-check the resulting Python file.
            # This catches real breakage (mismatched braces, broken indentation)
            # without false-positives on partial-line fragments.
            if language.lower() == "python" and not any(path in e for e in errors):
                patched = source
                applied_all = True
                for ch in changes:
                    old = ch.get("old_code") or ""
                    new = ch.get("new_code") or ""
                    if old and old in patched:
                        patched = patched.replace(old, new, 1)
                    elif old:
                        applied_all = False
                        break
                    elif new:
                        patched = patched + "\n" + new
                if applied_all:
                    try:
                        ast.parse(patched)
                    except SyntaxError as e:
                        errors.append(
                            f"{path}: patched file has Python SyntaxError at line "
                            f"{e.lineno}: {e.msg}"
                        )

    except Exception as exc:
        logger.warning("[patch_validate] validator crashed: %s", exc)
        # Fail-open if validator itself errors — patch_engine + post-patch tests are the safety net.
        return True, []

    return (len(errors) == 0), errors


def build_patch_repair_prompt(
    issue: Dict,
    bad_fix: Dict,
    errors: List[str],
    files: Dict[str, str],
) -> str:
    """Focused correction prompt that shows the model exactly what didn't match."""
    fix_json = json.dumps(bad_fix.get("fix", {}), indent=2)[:1500]

    file_excerpts: List[str] = []
    referenced_paths = {
        (fe.get("path") or "") for fe in (bad_fix.get("fix") or {}).get("files", [])
    }
    for path in referenced_paths:
        if not path:
            continue
        content = files.get(path)
        if content is None:
            base = path.split("/")[-1]
            for k, v in files.items():
                if k.endswith(base):
                    path, content = k, v
                    break
        if content is None:
            continue
        # Show first 60 + last 30 lines so the model can re-locate old_code
        lines = content.splitlines()
        if len(lines) > 100:
            shown = "\n".join(lines[:60]) + "\n# ... truncated ...\n" + "\n".join(lines[-30:])
        else:
            shown = content
        file_excerpts.append(f"### {path}\n```\n{shown[:6000]}\n```")

    return (
        "Your previously proposed patch is invalid. The patch engine pre-flight "
        "check found these problems:\n\n"
        + "\n".join(f"- {e}" for e in errors[:10])
        + "\n\n## Your previous fix (which is wrong)\n```json\n" + fix_json + "\n```\n\n"
        + "## Actual file contents (use these to write old_code that matches EXACTLY)\n"
        + "\n\n".join(file_excerpts) + "\n\n"
        + "## Task\nRewrite the fix JSON. For each change, old_code MUST appear verbatim "
        + "in the file above (matching whitespace and indentation). Output ONLY the JSON "
        + "object with the same schema as before."
    )


# ─── 4. Chain-of-Verification ────────────────────────────────────────────────

UNIVERSAL_COVE_QUESTIONS = [
    "Does the old_code in every change appear verbatim in its target file?",
    "Could this change break callers of the modified function/method?",
    "Are there null, empty, or boundary inputs the change does not handle?",
    "Does the change introduce any new exception path that callers don't expect?",
]


def build_cove_prompt(issue: Dict, fix_result: Dict, question: str) -> str:
    fix_snippet = json.dumps(fix_result.get("fix", {}), indent=2)[:1500]
    return (
        "You are verifying a proposed code fix. Answer ONE specific question honestly.\n\n"
        f"## Issue\n{issue.get('title', '')[:200]}\n\n"
        f"## Proposed fix\n```json\n{fix_snippet}\n```\n\n"
        f"## Question\n{question}\n\n"
        "Respond with ONLY valid JSON:\n"
        '{"answer": "yes" or "no", "explanation": "<one sentence>", "concern_level": <0-10>}'
    )


def chain_of_verification(
    issue: Dict,
    fix_result: Dict,
    call_ollama_extract,
    parse_response,
    model: str = "",
    role_primer: str = "",
) -> Dict:
    """
    Generate question-specific independent answers and aggregate into a verdict.

    Each question is answered in its own short call so the model can't smear
    one answer across the others. High-concern answers tilt the verdict toward
    'revise'. Always returns a verdict dict, even on partial failure.
    """
    questions = list(UNIVERSAL_COVE_QUESTIONS)

    # Add up to 2 fix-specific questions derived from the model's stated risks
    risks = (fix_result.get("chain_of_thought") or {}).get("risks", "")
    if risks and len(risks) > 30:
        questions.append(f"The author noted these risks: '{risks[:200]}'. Did the fix actually mitigate them?")

    concerns: List[Dict] = []
    answers: List[Dict] = []
    for q in questions[:5]:
        try:
            prompt = build_cove_prompt(issue, fix_result, q)
            raw = call_ollama_extract(prompt, system=role_primer, model=model)
            parsed = parse_response(raw)
            if not parsed:
                continue
            answers.append({"q": q, **parsed})
            level = int(parsed.get("concern_level", 0) or 0)
            answer = (parsed.get("answer") or "").strip().lower()
            # A "no" to a positive-framed safety question means there IS a problem
            negative_framed = q.startswith(("Does the old_code", "Does this not"))
            problematic = (answer == "no" and negative_framed) or (answer == "yes" and not negative_framed and level >= 6) or (level >= 7)
            if problematic:
                concerns.append({"q": q, "explanation": parsed.get("explanation", ""), "level": level})
        except Exception as exc:
            logger.debug("[cove] question skipped: %s", exc)

    verdict = "approve"
    notes = ""
    if any(c["level"] >= 7 for c in concerns):
        verdict = "revise"
        notes = " | ".join(f"{c['q'][:60]}: {c['explanation'][:120]}" for c in concerns[:3])
    elif len(concerns) >= 2:
        verdict = "revise"
        notes = " | ".join(f"{c['q'][:60]}: {c['explanation'][:120]}" for c in concerns[:3])

    return {
        "verdict": verdict,
        "concerns": concerns,
        "answers_count": len(answers),
        "revision_notes": notes,
    }


# ─── 5. Failure post-mortem RAG ──────────────────────────────────────────────

FAILURE_MEMORY_NAMESPACE = "repair_failures"


def remember_failed_repair(issue: Dict, fix_result: Optional[Dict], failure_reason: str) -> None:
    try:
        from memory.persistent_memory import get_memory
        fix_snippet = ""
        if fix_result:
            fix_snippet = json.dumps(fix_result.get("fix", {}))[:600]
        content = (
            f"FAILED ISSUE: {issue.get('title', '')[:200]}\n"
            f"BODY: {(issue.get('body') or '')[:400]}\n"
            f"FAILURE REASON: {failure_reason[:400]}\n"
            f"REJECTED FIX: {fix_snippet}"
        )
        metadata = {
            "issue_url": issue.get("issue_url", ""),
            "language": issue.get("language", ""),
            "failure_reason": failure_reason[:120],
        }
        get_memory().remember(FAILURE_MEMORY_NAMESPACE, content, metadata)
    except Exception as exc:
        logger.debug("[failure_rag] persistence skipped: %s", exc)


def retrieve_similar_past_failures(issue: Dict, limit: int = 1) -> List[Dict]:
    try:
        from memory.persistent_memory import get_memory
        query = f"{issue.get('title', '')}\n{(issue.get('body') or '')[:600]}"
        return get_memory().recall(FAILURE_MEMORY_NAMESPACE, query, limit=limit) or []
    except Exception as exc:
        logger.debug("[failure_rag] retrieval skipped: %s", exc)
        return []


def format_past_failures_for_prompt(hits: List[Dict]) -> str:
    if not hits:
        return ""
    blocks = ["## Anti-patterns from past FAILED repairs (avoid these mistakes)"]
    for i, hit in enumerate(hits[:1], 1):
        blocks.append(f"\n### Past failure {i} (similarity={hit.get('score', 0):.2f})\n{hit.get('content', '')[:900]}")
    return "\n".join(blocks) + "\n"


# ─── 6. Adaptive few-shot from RAG hit ───────────────────────────────────────

def build_adaptive_few_shot(rag_hits: List[Dict]) -> str:
    """
    Convert the top RAG hit (a past successful repair) into a few-shot block.
    Returns "" if no usable hit; caller falls back to the hardcoded example.
    """
    if not rag_hits:
        return ""
    hit = rag_hits[0]
    if (hit.get("score") or 0) < 0.3:
        return ""
    body = hit.get("content") or ""
    if "DIAGNOSIS:" not in body or "FIX:" not in body:
        return ""
    return (
        "## Adaptive few-shot — a real past success on a similar issue in your memory\n"
        f"(similarity {hit.get('score', 0):.2f})\n\n"
        f"{body[:1400]}\n\n"
        "Use the SAME json schema. Make YOUR fix as targeted and minimal as that past success.\n"
    )


# ─── 7. Symbol resolution ────────────────────────────────────────────────────

_PY_DEF_RE = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+(\w+)\s*[\(:]", re.MULTILINE)
_JS_DEF_RE = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s*)?\(?[^=]*=>|class\s+(\w+))",
    re.MULTILINE,
)


def _extract_mentioned_symbols(text: str) -> List[str]:
    """Find identifiers mentioned in diagnostic text — both bare and dotted."""
    if not text:
        return []
    # Dotted refs (foo.bar) and capitalised/snake-case identifiers
    candidates = re.findall(r"\b([A-Z][a-zA-Z0-9_]+|[a-z_][a-zA-Z0-9_]*(?:\.[a-z_][a-zA-Z0-9_]*)+|[a-z_][a-zA-Z0-9_]{3,})\b", text)
    stop = {
        "this", "that", "with", "from", "into", "when", "issue", "bug", "fix",
        "code", "file", "files", "path", "test", "tests", "value", "should",
        "would", "could", "true", "false", "None", "null", "self", "return",
        "function", "method", "class", "module", "import",
    }
    seen: set = set()
    out: List[str] = []
    for c in candidates:
        if c in stop or c.lower() in stop:
            continue
        if c not in seen:
            seen.add(c)
            out.append(c)
        if len(out) >= 20:
            break
    return out


def resolve_symbols(
    diagnosis_text: str,
    files: Dict[str, str],
    language: str,
    max_defs: int = 6,
) -> List[Dict[str, str]]:
    """
    Locate definitions for symbols referenced in a diagnosis. Pure-local: grep
    over the loaded files. Returns [] on any failure.
    """
    if not diagnosis_text or not files:
        return []
    try:
        symbols = _extract_mentioned_symbols(diagnosis_text)
        if not symbols:
            return []

        defs: List[Dict[str, str]] = []
        lang = language.lower()

        for path, content in files.items():
            if not content:
                continue
            try:
                if lang == "python":
                    matches = _PY_DEF_RE.findall(content)
                else:
                    matches = []
                    for m in _JS_DEF_RE.findall(content):
                        for grp in m:
                            if grp:
                                matches.append(grp)
            except Exception:
                continue

            for name in matches:
                base = name.split(".")[-1]
                for sym in symbols:
                    sym_base = sym.split(".")[-1]
                    if sym_base == base:
                        # Pull the definition + a few following lines
                        try:
                            lines = content.splitlines()
                            for i, line in enumerate(lines):
                                if re.search(rf"\b(?:def|class|function|const|let|var)\s+{re.escape(name)}\b", line):
                                    snippet = "\n".join(lines[i:i + 8])[:600]
                                    defs.append({
                                        "symbol": sym,
                                        "definition_in": path,
                                        "snippet": snippet,
                                    })
                                    break
                        except Exception:
                            pass
                        break
                if len(defs) >= max_defs:
                    return defs
        return defs
    except Exception as exc:
        logger.debug("[symbols] resolution non-fatal: %s", exc)
        return []


def format_symbols_for_prompt(defs: List[Dict[str, str]]) -> str:
    if not defs:
        return ""
    parts = ["## Resolved Symbol Definitions (from the loaded files)"]
    for d in defs[:6]:
        parts.append(f"\n### `{d['symbol']}` (defined in {d['definition_in']})\n```\n{d['snippet']}\n```")
    return "\n".join(parts) + "\n"


# ─── 8. Caller impact analysis ───────────────────────────────────────────────

_LENIENT_SYMBOL_RE = re.compile(
    r"\b(?:def|class|function|const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)",
)


def analyze_caller_impact(
    fix_result: Dict,
    files: Dict[str, str],
) -> Dict[str, object]:
    """
    Find files (other than the ones being modified) that reference the symbols
    the fix touches. Surfaces blast radius without doing import-graph analysis.
    """
    report: Dict[str, object] = {"modified_symbols": [], "callers": [], "blast_radius": 0}
    try:
        fix = fix_result.get("fix") or {}
        file_changes = fix.get("files") or []
        modified_files = {(fc.get("path") or "") for fc in file_changes}

        # Extract symbols the fix introduces/modifies — lenient regex handles
        # partial old_code like `def generate_id` (no trailing paren).
        modified_symbols: List[str] = []
        for fc in file_changes:
            for ch in fc.get("changes") or []:
                for src in (ch.get("new_code") or "", ch.get("old_code") or ""):
                    if not src:
                        continue
                    for name in _LENIENT_SYMBOL_RE.findall(src):
                        if name and name not in modified_symbols and len(name) >= 3:
                            modified_symbols.append(name)
        report["modified_symbols"] = modified_symbols[:10]
        if not modified_symbols:
            return report

        # Grep other files for usage
        callers: List[Dict] = []
        for path, content in files.items():
            if path in modified_files or not content:
                continue
            for sym in modified_symbols:
                pattern = rf"\b{re.escape(sym)}\b"
                hits = len(re.findall(pattern, content))
                if hits > 0:
                    callers.append({"file": path, "symbol": sym, "references": hits})
        callers.sort(key=lambda c: -c["references"])
        report["callers"] = callers[:8]
        report["blast_radius"] = sum(c["references"] for c in callers)
    except Exception as exc:
        logger.debug("[caller_impact] non-fatal: %s", exc)
    return report


def format_caller_impact_for_prompt(report: Dict[str, object]) -> str:
    callers = report.get("callers") or []
    if not callers:
        return ""
    lines = [
        "## Caller Impact Analysis",
        f"Symbols modified: {', '.join(report.get('modified_symbols', []))}",
        f"Total references across other loaded files: {report.get('blast_radius', 0)}",
        "",
        "Files that use the modified symbols (handle their callers carefully):",
    ]
    for c in callers[:6]:
        lines.append(f"- {c['file']} — uses `{c['symbol']}` ({c['references']}×)")
    return "\n".join(lines) + "\n"


# ─── 9. Code-grounding verification ──────────────────────────────────────────

_QUOTED_CODE_RE = re.compile(r"`([^`\n]{8,200})`")


def verify_code_grounding(
    fix_result: Dict,
    files: Dict[str, str],
) -> Dict[str, object]:
    """
    Check that backtick-quoted code snippets in the diagnosis/CoT actually
    appear in the loaded files. If the model invented quotes, that's a strong
    hallucination signal.

    Returns {grounded, total, quotes_missing, ratio}.
    """
    report = {"grounded": 0, "total": 0, "quotes_missing": [], "ratio": 1.0}
    try:
        text_parts: List[str] = []
        diagnosis = fix_result.get("diagnosis", "")
        cot = fix_result.get("chain_of_thought") or {}
        text_parts.append(diagnosis)
        for k in ("root_cause", "minimal_change", "risks", "verification"):
            text_parts.append(str(cot.get(k, "")))
        text = "\n".join(text_parts)

        quotes = list(set(m.strip() for m in _QUOTED_CODE_RE.findall(text)))
        if not quotes:
            return report
        report["total"] = len(quotes)

        all_source = "\n".join(files.values())
        all_source_norm = _normalize_for_match(all_source)
        for q in quotes:
            if q in all_source or _normalize_for_match(q) in all_source_norm:
                report["grounded"] += 1
            else:
                report["quotes_missing"].append(q[:120])
        report["ratio"] = report["grounded"] / report["total"]
    except Exception as exc:
        logger.debug("[grounding] non-fatal: %s", exc)
    return report


# ─── 10. Test coverage detection ─────────────────────────────────────────────

def detect_test_coverage(
    files: Dict[str, str],
    fix_result: Dict,
    language: str,
) -> Dict[str, object]:
    """Locate test files that import or reference the modified files."""
    report = {"test_files_loaded": 0, "modified_files_covered": [], "modified_files_uncovered": []}
    try:
        fix = fix_result.get("fix") or {}
        modified_paths = [
            (fc.get("path") or "") for fc in (fix.get("files") or [])
            if (fc.get("path") or "")
        ]
        if not modified_paths:
            return report

        test_files: List[str] = []
        for path in files:
            p = path.lower()
            if "/test" in p or p.startswith("test") or p.endswith(("_test.py", "_test.js", ".test.js", ".test.ts", ".spec.js", ".spec.ts")):
                test_files.append(path)
            elif language.lower() == "python" and "test_" in path.split("/")[-1]:
                test_files.append(path)
        report["test_files_loaded"] = len(test_files)

        for path in modified_paths:
            module_name = path.replace("/", ".").rsplit(".", 1)[0]  # path/to/foo.py → path.to.foo
            short = path.split("/")[-1].rsplit(".", 1)[0]
            covered = False
            for tf in test_files:
                content = files.get(tf, "")
                if not content:
                    continue
                if short and (short in content or module_name in content):
                    covered = True
                    break
            if covered:
                report["modified_files_covered"].append(path)
            else:
                report["modified_files_uncovered"].append(path)
    except Exception as exc:
        logger.debug("[test_coverage] non-fatal: %s", exc)
    return report


def format_test_coverage_for_prompt(report: Dict[str, object]) -> str:
    uncov = report.get("modified_files_uncovered") or []
    if not uncov:
        return ""
    lines = ["## Test Coverage Warning"]
    lines.append("These files have NO matching tests in the loaded context — write tests if you touch them:")
    for p in uncov[:6]:
        lines.append(f"- {p}")
    return "\n".join(lines) + "\n"


# ─── 11. Diff minimality scoring ─────────────────────────────────────────────

def score_diff_minimality(fix_result: Dict) -> Dict[str, object]:
    """
    Measure how minimal the proposed diff is. Models tend to over-rewrite.
    Returns counts + a 0–10 minimality score (10 = surgical).
    """
    report = {
        "files_touched": 0,
        "total_changes": 0,
        "lines_added": 0,
        "lines_removed": 0,
        "minimality_score": 10,
    }
    try:
        fix = fix_result.get("fix") or {}
        file_changes = fix.get("files") or []
        report["files_touched"] = len(file_changes)
        for fc in file_changes:
            changes = fc.get("changes") or []
            report["total_changes"] += len(changes)
            for ch in changes:
                old = ch.get("old_code") or ""
                new = ch.get("new_code") or ""
                report["lines_removed"] += len(old.splitlines())
                report["lines_added"]   += len(new.splitlines())

        net = report["lines_added"] + report["lines_removed"]
        files_touched = report["files_touched"]

        score = 10
        if files_touched > 3:
            score -= 2 * (files_touched - 3)
        if net > 20:
            score -= min(5, (net - 20) // 10)
        if report["total_changes"] > 5:
            score -= (report["total_changes"] - 5)
        report["minimality_score"] = max(0, score)
    except Exception as exc:
        logger.debug("[minimality] non-fatal: %s", exc)
    return report


# ─── 12. Issue intent classification (local heuristic) ───────────────────────

_INTENT_PATTERNS = {
    "question": [
        r"\bhow do i\b", r"\bhow to\b", r"\bwhat is\b", r"\bwhy does\b",
        r"\bcan (?:i|you|we|someone)\b", r"\bany ideas\b", r"\?\s*$",
    ],
    "feature": [
        r"\bfeature request\b", r"\b(?:would|it would) be (?:nice|great|cool)\b",
        r"\bplease add\b", r"\bsupport for\b", r"\b\[feature\]\b", r"\benhancement\b",
        r"\bproposal\b", r"\brfc\b",
    ],
    "doc": [
        r"\bdocs?\b.*\b(?:typo|fix|update|wrong|missing)\b",
        r"\b(?:typo|spelling)\b.*\b(?:readme|doc)\b",
        r"\bdocumentation\b", r"\bjsdoc\b", r"\bdocstring\b",
    ],
    "duplicate": [
        r"\bduplicate of\b", r"\b/duplicate\b", r"\bdupe of\b", r"\bsee #\d+\b",
    ],
    "bug": [
        r"\b(?:error|exception|traceback|crash|broken|fails?|panic|segfault)\b",
        r"\b(?:doesn'?t work|not working|unexpected)\b", r"\bregression\b",
        r"\b\[bug\]\b",
    ],
}


def classify_issue_intent_local(title: str, body: str) -> Dict[str, object]:
    """
    Heuristic-only intent classifier (no LLM call). Returns:
      {"intent": str, "confidence": float, "should_attempt": bool}
    """
    text = f"{title}\n{body or ''}".lower()
    scores: Dict[str, int] = {k: 0 for k in _INTENT_PATTERNS}
    try:
        for intent, patterns in _INTENT_PATTERNS.items():
            for p in patterns:
                if re.search(p, text):
                    scores[intent] += 1
        # Tie-break: bug wins over question/feature when both fire, since
        # bug-like issues with questions in the body are still bugs.
        if scores["bug"] >= 2:
            chosen, conf = "bug", min(1.0, 0.5 + 0.15 * scores["bug"])
        else:
            chosen = max(scores, key=lambda k: scores[k])
            total = sum(scores.values())
            conf = (scores[chosen] / total) if total else 0.0
            if scores[chosen] == 0:
                chosen = "bug"  # default — most bounty platforms list bugs
                conf = 0.3

        should_attempt = chosen in ("bug", "doc")
        return {"intent": chosen, "confidence": round(conf, 2), "should_attempt": should_attempt}
    except Exception as exc:
        logger.debug("[intent] classification non-fatal: %s", exc)
        return {"intent": "bug", "confidence": 0.0, "should_attempt": True}


# ─── 13. Reasoning trace ─────────────────────────────────────────────────────

class ReasoningTrace:
    """
    Pipeline-wide decision log. Each stage records what it decided and why.
    Persisted with the result and stored in RAG metadata for later analysis.
    """

    def __init__(self) -> None:
        self.events: List[Dict[str, object]] = []

    def record(self, stage: str, decision: str, **details) -> None:
        try:
            entry: Dict[str, object] = {"stage": stage, "decision": decision}
            for k, v in details.items():
                # Keep traces JSON-serialisable and bounded
                if isinstance(v, (str, int, float, bool)) or v is None:
                    entry[k] = v
                else:
                    entry[k] = str(v)[:240]
            self.events.append(entry)
        except Exception:
            pass

    def to_list(self) -> List[Dict[str, object]]:
        return list(self.events)

    def summary(self) -> str:
        return " | ".join(f"{e.get('stage')}={e.get('decision')}" for e in self.events[-6:])
