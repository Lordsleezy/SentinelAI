"""
github_examples.py — Retrieve repo-specific repair examples from GitHub.

Searches the same repository for closed issues with matching keywords, then
fetches the linked PR diff. Injects this as targeted few-shot context — what
the *actual maintainer* has historically accepted.

Fails silently: every call returns an empty list on error so the repair
pipeline is never blocked by a network/API issue.
"""
import logging
import os
import re
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_API = "https://api.github.com"
HTTP_TIMEOUT = 8.0
MAX_EXAMPLES = 2
MAX_DIFF_CHARS = 1500


def _headers() -> Dict[str, str]:
    h = {"Accept": "application/vnd.github.v3+json", "User-Agent": "SentinelAI/1.0"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"token {GITHUB_TOKEN}"
    return h


def _extract_repo(issue_url: str) -> Optional[tuple]:
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/issues/(\d+)", issue_url)
    if not m:
        return None
    return m.group(1), m.group(2), int(m.group(3))


def _top_keywords(title: str, body: str, limit: int = 4) -> List[str]:
    stopwords = {
        "the", "a", "an", "is", "it", "in", "on", "at", "to", "for", "of",
        "and", "or", "but", "with", "this", "that", "when", "if", "not",
        "be", "have", "has", "do", "does", "issue", "bug", "fix", "error",
        "from", "by", "as", "i", "we", "you", "are", "was", "were",
    }
    text = f"{title} {body}"
    words = re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]{3,}\b", text)
    seen = set()
    out = []
    for w in words:
        lw = w.lower()
        if lw not in stopwords and lw not in seen:
            seen.add(lw)
            out.append(w)
        if len(out) >= limit:
            break
    return out


def _find_linked_pr(client: httpx.Client, owner: str, repo: str, issue_num: int) -> Optional[int]:
    """Inspect issue timeline for a closing PR reference."""
    try:
        url = f"{GITHUB_API}/repos/{owner}/{repo}/issues/{issue_num}/timeline"
        headers = _headers()
        headers["Accept"] = "application/vnd.github.mockingbird-preview+json"
        r = client.get(url, headers=headers, params={"per_page": 30})
        if r.status_code != 200:
            return None
        for event in r.json():
            if event.get("event") in ("closed", "cross-referenced"):
                src = event.get("source") or {}
                issue = src.get("issue") or {}
                if issue.get("pull_request"):
                    return int(issue.get("number"))
                commit_url = event.get("commit_url") or ""
                m = re.search(r"/pull/(\d+)", commit_url)
                if m:
                    return int(m.group(1))
    except Exception:
        pass
    return None


def _fetch_pr_diff(client: httpx.Client, owner: str, repo: str, pr_num: int) -> str:
    try:
        url = f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pr_num}"
        headers = _headers()
        headers["Accept"] = "application/vnd.github.v3.diff"
        r = client.get(url, headers=headers)
        if r.status_code != 200:
            return ""
        return r.text[:MAX_DIFF_CHARS]
    except Exception:
        return ""


def find_similar_resolved_issues(
    issue_url: str,
    title: str,
    body: str,
    max_examples: int = MAX_EXAMPLES,
) -> List[Dict[str, str]]:
    """
    Search the same repository for closed issues with similar keywords and
    return their linked PR diffs as few-shot examples.

    Returns [] on any failure — the caller treats this as an optional enhancement.
    """
    parsed = _extract_repo(issue_url)
    if not parsed:
        return []
    owner, repo, current_issue = parsed

    keywords = _top_keywords(title, body, limit=4)
    if not keywords:
        return []

    query = f"repo:{owner}/{repo} is:closed is:issue " + " ".join(keywords[:3])
    examples: List[Dict[str, str]] = []

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            r = client.get(
                f"{GITHUB_API}/search/issues",
                headers=_headers(),
                params={"q": query, "sort": "updated", "order": "desc", "per_page": 8},
            )
            if r.status_code == 403:
                logger.warning("[github_examples] Rate limit hit — skipping similar-issue lookup")
                return []
            if r.status_code != 200:
                logger.debug("[github_examples] search returned %s", r.status_code)
                return []

            for item in r.json().get("items", []):
                if len(examples) >= max_examples:
                    break
                num = item.get("number")
                if not num or num == current_issue:
                    continue

                pr_num = _find_linked_pr(client, owner, repo, num)
                if not pr_num:
                    continue
                diff = _fetch_pr_diff(client, owner, repo, pr_num)
                if not diff:
                    continue
                examples.append({
                    "issue_title": (item.get("title") or "")[:160],
                    "issue_number": str(num),
                    "pr_number": str(pr_num),
                    "diff": diff,
                })
    except Exception as exc:
        logger.warning("[github_examples] lookup failed (non-fatal): %s", exc)
        return []

    if examples:
        logger.info("[github_examples] retrieved %d repo-specific example(s)", len(examples))
    return examples


def format_examples_for_prompt(examples: List[Dict[str, str]]) -> str:
    """Render examples as a prompt block, empty string if none."""
    if not examples:
        return ""

    blocks = [
        "## Maintainer-Accepted Patterns From This Repo",
        "Past resolved issues in this same repository. Study what the maintainer accepts:",
    ]
    for ex in examples:
        blocks.append(
            f"\n### Closed issue #{ex['issue_number']}: {ex['issue_title']}\n"
            f"Accepted PR #{ex['pr_number']} diff (truncated):\n"
            f"```diff\n{ex['diff']}\n```"
        )
    return "\n".join(blocks) + "\n"
