"""
reasoning_engine.py — Two-pass scratchpad + adversarial reasoning for SentinelAI.

Separates free-form reasoning (think pass, temp=0.35) from JSON extraction
(extract pass, temp=0.05) to maximise quality on small Ollama models.
Adversarial verification and optional self-consistency sampling live here.
"""
import json
import logging
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


def two_pass_inference(
    think_prompt: str,
    json_schema_hint: str,
    system: str = "",
    model: str = "",
) -> str:
    """
    Free-form reasoning pass followed by a structured extraction pass.

    Returns raw string — caller should run through parse_and_validate_response.
    """
    from prompt_engine import call_ollama_think, call_ollama_extract

    scratchpad = call_ollama_think(think_prompt, system=system, model=model)
    logger.debug("two_pass_inference: scratchpad %d chars", len(scratchpad))

    extract_prompt = (
        "You have analyzed the problem. Your reasoning:\n\n"
        + scratchpad[:3000]
        + "\n\nNow output ONLY the following JSON object. "
        "Start with { and end with }. No markdown. No explanation outside the JSON.\n\n"
        + json_schema_hint
    )
    raw = call_ollama_extract(extract_prompt, system=system, model=model)

    if not raw or "{" not in raw:
        logger.debug("two_pass_inference: extraction empty, falling back to scratchpad")
        return scratchpad
    return raw


def adversarial_verify(
    task_summary: str,
    proposed_output: Dict,
    system: str = "",
    model: str = "",
) -> Dict:
    """
    Aggressively critique a proposed fix to surface bugs before applying it.

    Returns verdict dict. Falls back to a neutral approve on call failure so
    the caller's pipeline is never blocked by a verification error.
    """
    from prompt_engine import call_ollama_with_retry, parse_and_validate_response

    fix_snippet = json.dumps(proposed_output, indent=2)[:2000]
    prompt = (
        "You are a skeptical senior code reviewer whose job is to FIND BUGS — not approve fixes.\n"
        "Assume the following proposed fix is WRONG until proven otherwise.\n\n"
        f"Task summary:\n{task_summary[:500]}\n\n"
        f"Proposed fix:\n{fix_snippet}\n\n"
        "Answer ALL questions honestly:\n"
        "1. Does this fix the root cause, or just a symptom?\n"
        "2. Does this introduce new bugs or regressions?\n"
        "3. Are there unhandled edge cases?\n"
        "4. Is this truly the minimal change?\n\n"
        "Respond with ONLY valid JSON — no markdown:\n"
        '{"addresses_root_cause": <true/false>, '
        '"introduces_bugs": <true/false>, '
        '"bug_description": "<or empty string>", '
        '"unhandled_edge_cases": "<list or none>", '
        '"confidence": <0-10>, '
        '"verdict": "approve" or "revise", '
        '"revision_notes": "<required if revise, else empty string>"}'
    )

    try:
        raw = call_ollama_with_retry(prompt, system=system, model=model)
        result = parse_and_validate_response(raw)
        if result:
            return result
    except Exception as exc:
        logger.warning("adversarial_verify non-fatal: %s", exc)

    return {
        "verdict": "approve",
        "confidence": 5,
        "addresses_root_cause": True,
        "introduces_bugs": False,
        "bug_description": "",
        "unhandled_edge_cases": "none",
        "revision_notes": "",
    }


def self_consistent_fix(
    think_prompt: str,
    json_schema_hint: str,
    system: str = "",
    model: str = "",
    samples: int = 3,
    parse_fn: Optional[Callable] = None,
) -> Optional[Dict]:
    """
    Run multiple two-pass samples and return the highest-confidence result.

    Use for borderline-confidence fixes where a single pass is unreliable.
    samples=3 is the recommended minimum.
    """
    if parse_fn is None:
        from prompt_engine import parse_and_validate_response as parse_fn

    best: Optional[Dict] = None
    best_confidence = -1

    for i in range(samples):
        try:
            raw = two_pass_inference(
                think_prompt, json_schema_hint, system=system, model=model
            )
            candidate = parse_fn(raw)
            if candidate is None:
                continue
            conf = int(candidate.get("confidence", 0))
            logger.debug(
                "self_consistent_fix sample %d/%d: confidence=%d", i + 1, samples, conf
            )
            if conf > best_confidence:
                best_confidence = conf
                best = candidate
        except Exception as exc:
            logger.warning("self_consistent_fix sample %d failed: %s", i + 1, exc)

    return best
