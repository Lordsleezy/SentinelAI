"""
prompt_engine.py — Advanced Ollama prompt engineering for Sentinel Earn
Implements 8 techniques to maximise qwen2.5-coder:14b output quality

Techniques:
  1. Chain-of-thought forcing
  2. Role priming
  3. Structured output enforcement + schema validation
  4. Context compression (token budget aware)
  5. Self-verification loop
  6. Retry with simplification
  7. Language-specific instructions
  8. Complexity gating
"""
import json
import re
import time
import logging
from typing import Optional, Dict, List
import httpx
from dotenv import load_dotenv
import os

load_dotenv()

OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434") + "/api/generate"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder:14b")
MAX_CODE_CHARS = 8000 * 4  # ~8 000 tokens × 4 chars/token

logger = logging.getLogger(__name__)


# ─── 2. Role Priming ──────────────────────────────────────────────────────────

ROLE_PRIMER = (
    "You are a senior software engineer with 15 years of experience. "
    "You have reviewed thousands of bug reports and your fixes are precise, minimal, "
    "and always include your reasoning. "
    "You never guess — if you are not confident, you say so clearly. "
    "You write clean, idiomatic code that follows the language's best practices. "
    "You prefer surgical, minimal changes over rewrites."
)


# ─── 7. Language-Specific Instructions ───────────────────────────────────────

LANG_RULES: Dict[str, str] = {
    "python": (
        "Python-specific rules:\n"
        "- Follow PEP 8 strictly.\n"
        "- Use type hints for all function signatures.\n"
        "- No global mutable variables.\n"
        "- Use f-strings for string formatting.\n"
        "- Prefer pathlib over os.path.\n"
        "- Use context managers for file/resource handling."
    ),
    "javascript": (
        "JavaScript-specific rules:\n"
        "- Use const/let, never var.\n"
        "- Handle all promise rejections with .catch() or try/catch.\n"
        "- Use optional chaining (?.) for nullable access.\n"
        "- Prefer arrow functions for callbacks.\n"
        "- Use template literals for string interpolation.\n"
        "- Use === not ==.\n"
        "- Destructure where it improves clarity."
    ),
    "typescript": (
        "TypeScript-specific rules:\n"
        "- Maintain strict typing throughout.\n"
        "- No 'any' types — use 'unknown' then narrow if uncertain.\n"
        "- Define interfaces for all object shapes.\n"
        "- Use type guards for runtime checks.\n"
        "- Export types alongside functions.\n"
        "- Prefer readonly for immutable props."
    ),
}


# ─── 4. Context Compression ──────────────────────────────────────────────────

def compress_context(files: Dict[str, str], issue_keywords: List[str]) -> str:
    """
    Compress file context intelligently to fit within MAX_CODE_CHARS.
    - Only files that are actually relevant (keyword hit or small enough).
    - Strip blank lines.
    - Long files: first 50 + last 50 + up to 30 keyword-containing lines.
    - Hard stop at MAX_CODE_CHARS total.
    """
    kws = [k.lower() for k in issue_keywords if len(k) > 2]
    parts: List[str] = []
    budget = MAX_CODE_CHARS

    for filename, content in files.items():
        if not content or not content.strip():
            continue
        if budget <= 0:
            parts.append(f"\n### FILE: {filename}\n[Budget exhausted — omitted]\n")
            continue

        lines = [ln for ln in content.split("\n") if ln.strip()]  # strip blank lines

        # Find keyword-containing lines
        kw_lines: List[tuple] = []
        for i, ln in enumerate(lines):
            if any(kw in ln.lower() for kw in kws):
                kw_lines.append((i, ln))

        if len(lines) <= 120:
            body = "\n".join(lines)
        else:
            head = lines[:50]
            tail = lines[-50:]
            head_tail_idx = set(range(50)) | set(range(len(lines) - 50, len(lines)))
            extra = [(i, ln) for i, ln in kw_lines if i not in head_tail_idx][:30]
            omitted = len(lines) - 100 - len(extra)

            sections = ["\n".join(head)]
            if extra:
                sections.append(f"\n# ... [{omitted} lines omitted, {len(extra)} keyword lines below] ...\n")
                sections.extend(f"# L{i+1}: {ln}" for i, ln in extra)
            sections.append(f"\n# ... [tail] ...\n")
            sections.append("\n".join(tail))
            body = "\n".join(sections)

        section = f"\n### FILE: {filename}\n```\n{body}\n```\n"
        budget -= len(section)
        parts.append(section)

    return "\n".join(parts) if parts else "(No relevant source files found)"


# ─── Prompt Builders ─────────────────────────────────────────────────────────

def build_complexity_assessment_prompt(title: str, body: str) -> str:
    """8. Ask model to self-assess complexity before attempting a fix."""
    return f"""{ROLE_PRIMER}

Assess the complexity of fixing this GitHub issue on a scale of 1–10.

Issue Title: {title}
Issue Body:
{body[:2000]}

Complexity scale:
  1–3  straightforward (typo, missing null-check, simple off-by-one)
  4–5  moderate (multi-file change, understand one subsystem)
  6–7  involved (design understanding required)
  8–10 complex (architecture change, perf, security, concurrency)

If complexity > 5, recommend skipping this issue.

Respond with ONLY a valid JSON object — no markdown, no text outside the JSON:
{{
    "complexity": <integer 1-10>,
    "reasoning": "<one sentence>",
    "should_attempt": <true if complexity <= 5, else false>,
    "skip_reason": "<required only when should_attempt is false>"
}}"""


def build_fix_prompt(issue: Dict, code_context: str, language: str) -> str:
    """
    Main fix prompt.
    Technique 1 (CoT) + Technique 2 (role) + Technique 3 (structured JSON)
    + Technique 7 (language rules).
    """
    lang_rules = LANG_RULES.get(language.lower(), "")
    comments_block = ""
    if issue.get("comments"):
        joined = "\n---\n".join(c[:500] for c in issue["comments"][:5])
        comments_block = f"\nIssue Comments (latest 5):\n{joined}\n"

    return f"""{ROLE_PRIMER}

{lang_rules}

You are fixing a GitHub issue. You MUST reason step-by-step BEFORE writing any code.

## Issue
Title: {issue.get("title", "")}
URL:   {issue.get("issue_url", "")}
Body:
{(issue.get("body") or "")[:3000]}
{comments_block}
## Relevant Code
{code_context}

## Chain of Thought (complete ALL 5 steps before writing code)
1. What is the EXACT root cause of this bug?
2. Which specific files and line numbers are involved?
3. What is the MINIMAL change that fixes it?
4. What could go wrong with this fix?
5. How would you verify it works?

## Output — STRICT JSON
You MUST respond with ONLY a valid JSON object. No markdown. No explanation outside the JSON.
If you cannot fix this with confidence >= 7, set confidence < 7 and explain in diagnosis.

{{
    "chain_of_thought": {{
        "root_cause":    "<exact root cause>",
        "files_involved": ["<file1>", "<file2>"],
        "minimal_change": "<description of the minimal fix>",
        "risks":         "<potential issues with this fix>",
        "verification":  "<how to verify it works>"
    }},
    "diagnosis":  "<concise technical explanation>",
    "fix": {{
        "files": [
            {{
                "path":   "<relative file path>",
                "action": "modify|create|delete",
                "changes": [
                    {{
                        "description": "<what this change does>",
                        "old_code":    "<exact code to replace — empty string for pure additions>",
                        "new_code":    "<replacement code>"
                    }}
                ]
            }}
        ]
    }},
    "confidence":  <integer 0-10>,
    "explanation": "<brief fix description for PR body>"
}}"""


def build_verification_prompt(issue: Dict, proposed_fix: Dict) -> str:
    """5. Self-verification — send the proposed fix back for critical review."""
    fix_json = json.dumps(proposed_fix.get("fix", {}), indent=2)[:2000]
    return f"""{ROLE_PRIMER}

You previously proposed a fix for this issue. Now review it critically.

## Original Issue
Title: {issue.get("title", "")}
Body:  {(issue.get("body") or "")[:1500]}

## Your Proposed Fix
{fix_json}

## Critical Review — answer ALL questions honestly:
1. Does this fix address the root cause (not just a symptom)?
2. Could this fix introduce new bugs or regressions?
3. Is this truly the minimal change needed?
4. Are there edge cases not handled?

Respond with ONLY a valid JSON object, no markdown:
{{
    "addresses_root_cause": <true/false>,
    "introduces_bugs":      <true/false>,
    "bug_description":      "<describe any new bugs, or empty string>",
    "is_minimal":           <true/false>,
    "unhandled_edge_cases": "<list any edge cases, or 'none'>",
    "confidence":           <integer 0-10>,
    "verdict":              "approve|revise",
    "revision_notes":       "<required if verdict is revise>"
}}"""


def build_retry_prompt(issue: Dict, failed_attempt: str, reason: str) -> str:
    """6. Simplification retry — strip away complexity, one-line focus."""
    return f"""{ROLE_PRIMER}

A previous fix attempt failed or had low confidence.
Reason: {reason}

The previous analysis was too complex. Focus ONLY on this:
{issue.get("title", "")}

Issue body (truncated):
{(issue.get("body") or "")[:800]}

Previous attempt (for reference — do NOT repeat its mistakes):
{failed_attempt[:400]}

New instructions:
- What is the ONE line or function that needs to change?
- Make the smallest possible fix that addresses the issue title.
- If you still can't be confident, set confidence < 7 and explain why.

Respond with ONLY a valid JSON object, no markdown:
{{
    "diagnosis":  "<one sentence: what needs to change>",
    "fix": {{
        "files": [
            {{
                "path":   "<file path>",
                "action": "modify",
                "changes": [
                    {{
                        "description": "<what this change does>",
                        "old_code":    "<exact code to replace>",
                        "new_code":    "<replacement code>"
                    }}
                ]
            }}
        ]
    }},
    "confidence":  <integer 0-10>,
    "explanation": "<brief fix description>"
}}"""


# ─── 3. Response Parsing & Validation ────────────────────────────────────────

def parse_and_validate_response(response: str) -> Optional[Dict]:
    """
    Extract and validate JSON from model output.
    Handles markdown fences, leading/trailing prose, partial drift.
    """
    if not response:
        return None

    cleaned = response.strip()

    # Strip markdown code fence if present
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    else:
        # Find outermost braces
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1]
        else:
            logger.debug(f"No JSON object found in response: {response[:100]}")
            return None

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        # Attempt relaxed parse — remove trailing commas (common model error)
        try:
            fixed = re.sub(r",\s*([\}\]])", r"\1", cleaned)
            data = json.loads(fixed)
        except json.JSONDecodeError:
            logger.warning(f"JSON parse failed: {exc} | snippet: {cleaned[:150]}")
            return None

    # Normalise confidence to int
    if "confidence" in data:
        try:
            data["confidence"] = int(float(data["confidence"]))
        except (ValueError, TypeError):
            data["confidence"] = 0

    # Validate fix structure when present
    if "fix" in data:
        if not isinstance(data["fix"].get("files"), list):
            logger.warning("Fix response missing 'files' list")
            return None

    return data


def _correction_prompt(bad_response: str, original_task_snippet: str) -> str:
    """Schema-correction prompt when model drifts from JSON."""
    return (
        f"Your previous response was not valid JSON.\n"
        f"What you responded (first 300 chars):\n{bad_response[:300]}\n\n"
        f"Original task summary: {original_task_snippet[:200]}\n\n"
        "You MUST respond with ONLY a raw JSON object.\n"
        "No markdown. No ```json fences. No text before or after.\n"
        "Start your response with { and end with }.\n"
        "Provide the same information as before in valid JSON."
    )


# ─── Ollama API ───────────────────────────────────────────────────────────────

def call_ollama(prompt: str, temperature: float = 0.1) -> str:
    """Single synchronous Ollama call."""
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "top_p": 0.9,
            "num_predict": 4096,
        },
    }
    resp = httpx.post(OLLAMA_URL, json=payload, timeout=180.0)
    resp.raise_for_status()
    return resp.json().get("response", "")


def call_ollama_with_retry(prompt: str, max_retries: int = 3) -> str:
    """
    Call Ollama with exponential backoff.
    On schema drift tries a correction prompt before giving up.
    """
    last_raw = ""
    last_err: Optional[Exception] = None

    for attempt in range(max_retries):
        try:
            raw = call_ollama(prompt)
            last_raw = raw

            if raw and "{" in raw:
                parsed = parse_and_validate_response(raw)
                if parsed is not None:
                    return raw  # ✓ Good response

                # Schema drift — inject correction on non-final attempts
                if attempt < max_retries - 1:
                    logger.warning(f"Schema drift (attempt {attempt+1}) — retrying with correction")
                    prompt = _correction_prompt(raw, prompt[:200])
                    time.sleep(2 ** attempt)
                    continue

            # Empty or non-JSON — just retry
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue

            return raw  # Return whatever we have on last attempt

        except httpx.ConnectError as e:
            last_err = e
            logger.error(f"Ollama not reachable at {OLLAMA_URL} — is it running?")
        except httpx.TimeoutException as e:
            last_err = e
            logger.warning(f"Ollama timeout (attempt {attempt+1})")
        except Exception as e:
            last_err = e
            logger.error(f"Ollama error (attempt {attempt+1}): {e}")

        if attempt < max_retries - 1:
            wait = 2 ** attempt
            logger.info(f"Retrying in {wait}s…")
            time.sleep(wait)

    raise RuntimeError(
        f"Ollama failed after {max_retries} attempts. "
        f"Last error: {last_err}. "
        f"Last response snippet: {last_raw[:200]}"
    )


# ─── Public helpers ───────────────────────────────────────────────────────────

def _extract_keywords(text: str) -> List[str]:
    """Extract meaningful identifiers / terms from issue text."""
    stopwords = {
        "the", "a", "an", "is", "it", "in", "on", "at", "to", "for", "of",
        "and", "or", "but", "with", "this", "that", "when", "if", "not",
        "be", "been", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "must", "can", "as",
        "from", "by", "are", "was", "were", "i", "we", "you", "he", "she",
        "they", "my", "your", "our", "its", "issue", "bug", "fix", "error",
        "problem", "please", "help", "need", "want", "get", "set",
    }
    words = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{2,}\b", text)
    seen: set = set()
    result: List[str] = []
    for w in words:
        lw = w.lower()
        if lw not in stopwords and lw not in seen:
            result.append(w)
            seen.add(lw)
        if len(result) >= 40:
            break
    return result


# ─── Full Fix Pipeline ────────────────────────────────────────────────────────

def assess_complexity(issue: Dict) -> Optional[Dict]:
    """8. Complexity gate — returns parsed result or None on error."""
    prompt = build_complexity_assessment_prompt(
        issue.get("title", ""), issue.get("body", "") or ""
    )
    try:
        raw = call_ollama_with_retry(prompt)
        return parse_and_validate_response(raw)
    except Exception as e:
        logger.error(f"Complexity assessment error: {e}")
        return None


def run_fix_pipeline(
    issue: Dict, files: Dict[str, str], language: str, dry_run: bool = False
) -> Optional[Dict]:
    """
    Full 8-step fix pipeline.

    Returns:
      {"skipped": True, "reason": "...", "complexity": n}  — skipped by gate
      {"dry_run": True, ...}                               — dry run info
      {"confidence": n, "fix": {...}, ...}                 — real result
      None                                                  — all attempts failed
    """
    # ── Step 1: Complexity gate ───────────────────────────────────────────────
    logger.info(f"Assessing complexity: {issue.get('title', '')[:60]}")
    cx_result = assess_complexity(issue)

    if cx_result:
        cx_score = cx_result.get("complexity", 5)
        if not cx_result.get("should_attempt", True):
            reason = cx_result.get("skip_reason", f"Complexity {cx_score}/10")
            logger.info(f"Skipping (complexity {cx_score}/10): {reason}")
            return {"skipped": True, "reason": reason, "complexity": cx_score}

    # ── Step 2: Extract keywords & compress context ───────────────────────────
    issue_text = issue.get("title", "") + " " + (issue.get("body", "") or "")
    keywords = _extract_keywords(issue_text)
    code_context = compress_context(files, keywords)
    logger.info(
        f"Context compressed: {len(files)} files → {len(code_context)} chars"
    )

    if dry_run:
        logger.info(
            f"[DRY RUN] Would run fix pipeline | language={language} "
            f"keywords={keywords[:5]} context_chars={len(code_context)}"
        )
        return {
            "dry_run": True,
            "would_attempt": True,
            "language": language,
            "context_chars": len(code_context),
            "keywords": keywords[:10],
        }

    # ── Step 3: Primary fix attempt ───────────────────────────────────────────
    fix_prompt = build_fix_prompt(issue, code_context, language)
    logger.info(f"Sending fix prompt ({len(fix_prompt)} chars) to Ollama…")
    result: Optional[Dict] = None

    try:
        raw = call_ollama_with_retry(fix_prompt)
        result = parse_and_validate_response(raw)
    except Exception as e:
        logger.error(f"Primary fix prompt failed: {e}")

    primary_confidence = result.get("confidence", 0) if result else 0

    # ── Step 4: Retry with simplification if confidence low ───────────────────
    if primary_confidence < 7:
        logger.info(
            f"Confidence {primary_confidence}/10 — retrying with simplified prompt…"
        )
        retry_reason = (
            f"Confidence was {primary_confidence}/10"
            if result
            else "Primary attempt returned no result"
        )
        failed_str = json.dumps(result, indent=2)[:400] if result else "No result"
        retry_prompt = build_retry_prompt(issue, failed_str, retry_reason)

        try:
            raw2 = call_ollama_with_retry(retry_prompt)
            retry_result = parse_and_validate_response(raw2)
            if retry_result:
                if retry_result.get("confidence", 0) > primary_confidence:
                    logger.info(
                        f"Retry improved confidence: "
                        f"{primary_confidence} → {retry_result['confidence']}"
                    )
                    result = retry_result
        except Exception as e:
            logger.error(f"Retry prompt failed: {e}")

    if result is None:
        logger.error("All fix attempts returned no parseable result")
        return None

    # ── Step 5: Self-verification ─────────────────────────────────────────────
    confidence = result.get("confidence", 0)
    if confidence >= 6:
        logger.info(f"Verifying fix (confidence={confidence})…")
        v_prompt = build_verification_prompt(issue, result)
        try:
            raw_v = call_ollama_with_retry(v_prompt)
            v = parse_and_validate_response(raw_v)
            if v:
                v_conf = v.get("confidence", confidence)
                if v.get("verdict") == "revise":
                    logger.info(f"Verification: revise — {v.get('revision_notes', '')}")
                    result["verification_verdict"] = "revise"
                    result["revision_notes"] = v.get("revision_notes", "")
                    result["confidence"] = min(confidence, v_conf)
                else:
                    result["verified"] = True
                    result["confidence"] = v_conf
                    logger.info(f"Verification approved (confidence={v_conf})")
        except Exception as e:
            logger.warning(f"Verification step non-fatal error: {e}")

    return result
