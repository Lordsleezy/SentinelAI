"""
groq_verifier.py — Cross-model adversarial verification via Groq free tier.

A genuinely independent reviewer is categorically stronger than self-review.
Groq's free tier provides LLaMA 3.3 70B at 14,400 requests/day with no card.

Fails silently: every public function returns None or a sensible default if
GROQ_API_KEY is absent or the call fails. The repair pipeline never blocks
on this enhancement.
"""
import json
import logging
import os
import re
from typing import Dict, Optional

import httpx

logger = logging.getLogger(__name__)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
HTTP_TIMEOUT = 25.0


def is_available() -> bool:
    return bool(GROQ_API_KEY)


def _parse_json_response(text: str) -> Optional[Dict]:
    if not text:
        return None
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        text = text[start : end + 1]
    try:
        return json.loads(text)
    except Exception:
        try:
            return json.loads(re.sub(r",\s*([\}\]])", r"\1", text))
        except Exception:
            return None


def cross_verify_fix(issue: Dict, proposed_fix: Dict) -> Optional[Dict]:
    """
    Ask a different model (LLaMA 70B via Groq) to adversarially review the
    proposed fix. Returns the verdict dict, or None if Groq is unavailable
    or the call fails.

    The repair pipeline treats None as "no second opinion available" and
    continues with the local-only verdict.
    """
    if not is_available():
        return None

    fix_snippet = json.dumps(proposed_fix.get("fix", {}), indent=2)[:2500]
    cot = proposed_fix.get("chain_of_thought", {})
    diagnosis = proposed_fix.get("diagnosis", "")

    system = (
        "You are a skeptical senior code reviewer. Your job is to FIND BUGS "
        "in proposed fixes, not approve them. Assume the fix is wrong until "
        "proven otherwise. You catch subtle errors that the original author "
        "missed. You always respond with valid JSON only — no markdown, "
        "no commentary outside the JSON object."
    )

    user = f"""Another model (qwen2.5-coder:14b) proposed this fix. Review it critically.

## Original Issue
Title: {issue.get("title", "")[:200]}
Body:  {(issue.get("body") or "")[:1200]}

## The Proposed Diagnosis
{diagnosis[:500]}

## The Proposed Reasoning
- Root cause:    {cot.get("root_cause", "")[:300]}
- Minimal change: {cot.get("minimal_change", "")[:300]}
- Risks:         {cot.get("risks", "")[:200]}

## The Proposed Code Changes
{fix_snippet}

## Your Critical Review
Answer ALL of these honestly:
1. Does this fix the ROOT cause, or just a symptom?
2. Does this introduce new bugs / regressions / side effects?
3. Are there edge cases the author missed (null, empty, async, concurrent, retries)?
4. Is the old_code → new_code mapping correct, or will the patcher fail to find old_code?
5. Is this the minimal change, or is it over-engineered?

Respond with ONLY this JSON:
{{
    "addresses_root_cause": <true/false>,
    "introduces_bugs":      <true/false>,
    "bug_description":      "<details, or empty>",
    "unhandled_edge_cases": "<list, or 'none'>",
    "patch_will_apply":     <true/false — will the old_code strings actually match?>,
    "is_minimal":           <true/false>,
    "confidence":           <integer 0-10>,
    "verdict":              "approve" | "revise" | "reject",
    "revision_notes":       "<required if verdict != approve>"
}}"""

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            r = client.post(
                GROQ_URL,
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json=payload,
            )
            if r.status_code == 429:
                logger.warning("[groq] daily rate limit reached — skipping cross-verification")
                return None
            if r.status_code != 200:
                logger.warning("[groq] HTTP %s: %s", r.status_code, r.text[:200])
                return None
            content = (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
            verdict = _parse_json_response(content)
            if verdict:
                logger.info(
                    "[groq] verdict=%s conf=%s patch_will_apply=%s",
                    verdict.get("verdict"),
                    verdict.get("confidence"),
                    verdict.get("patch_will_apply"),
                )
            return verdict
    except httpx.TimeoutException:
        logger.warning("[groq] timeout — skipping cross-verification")
        return None
    except Exception as exc:
        logger.warning("[groq] non-fatal failure: %s", exc)
        return None
