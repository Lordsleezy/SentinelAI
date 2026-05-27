"""
monitor.py — PR status monitor for Sentinel Earn
Polls submitted PRs every 30 minutes via GitHub API
Updates status: open → merged or closed
APScheduler job alongside scanner
"""
import os
import re
import logging
from typing import Optional, Dict, Tuple

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

import db

load_dotenv()

GITHUB_TOKEN             = os.getenv("GITHUB_TOKEN", "")
MONITOR_INTERVAL_MINUTES = 30

logger = logging.getLogger(__name__)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _gh_headers() -> Dict[str, str]:
    h = {"Accept": "application/vnd.github.v3+json", "User-Agent": "SentinelEarn/1.0"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"token {GITHUB_TOKEN}"
    return h


def _parse_pr_url(pr_url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract (owner, repo, pr_number) from a GitHub PR URL."""
    if not pr_url or "DRYRUN" in pr_url:
        return None, None, None
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/pull/(\d+)", pr_url)
    if not m:
        return None, None, None
    return m.groups()


def check_pr_status(owner: str, repo: str, pr_num: str) -> Optional[Dict]:
    """
    Query GitHub API for current PR state.
    Returns dict with keys: state, merged, merged_at
    Returns None on API error.
    """
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(
                f"https://api.github.com/repos/{owner}/{repo}/pulls/{pr_num}",
                headers=_gh_headers(),
            )
            if r.status_code == 200:
                pr = r.json()
                return {
                    "state":     pr.get("state", "open"),   # "open" | "closed"
                    "merged":    pr.get("merged", False),
                    "merged_at": pr.get("merged_at"),
                    "title":     pr.get("title", ""),
                }
            elif r.status_code == 404:
                return {"state": "not_found", "merged": False, "merged_at": None}
            else:
                logger.warning(
                    f"PR check {owner}/{repo}#{pr_num} returned {r.status_code}"
                )
                return None
    except Exception as e:
        logger.error(f"PR status check error: {e}")
        return None


# ─── Main monitor run ─────────────────────────────────────────────────────────

def run_monitor() -> Dict:
    """
    Check all pending/open submissions and update their status.
    Returns summary stats dict.
    """
    pending = db.list_pending_submissions()

    if not pending:
        logger.info("Monitor: no pending submissions")
        return {"checked": 0, "merged": 0, "closed": 0, "errors": 0}

    logger.info(f"Monitor: checking {len(pending)} pending submissions…")
    db.log_event("monitor_start", f"Checking {len(pending)} pending submissions")

    stats = {"checked": 0, "merged": 0, "closed": 0, "errors": 0}

    for sub in pending:
        pr_url = sub.get("pr_url", "")
        sub_id = sub["id"]
        opp_id = sub["opportunity_id"]
        bounty = sub.get("bounty_amount", 0) or 0

        owner, repo, pr_num = _parse_pr_url(pr_url)
        if not owner:
            logger.debug(f"Skipping non-parseable PR URL: {pr_url}")
            continue

        status = check_pr_status(owner, repo, pr_num)
        if status is None:
            stats["errors"] += 1
            continue

        stats["checked"] += 1

        if status["merged"]:
            # 🎉 Merged — record earnings
            earnings = bounty if bounty > 0 else 0.0
            db.update_submission_status(
                sub_id,
                status="merged",
                merged_at=status["merged_at"],
                earnings=earnings,
            )
            db.update_opportunity_status(opp_id, "merged")
            db.log_event(
                "pr_merged",
                f"PR merged! Earnings=${earnings:.2f} url={pr_url}",
                opp_id,
            )
            logger.info(f"🎉 PR merged: {pr_url}  |  Earnings: ${earnings:.2f}")
            stats["merged"] += 1

        elif status["state"] == "closed" and not status["merged"]:
            # Closed without merge
            db.update_submission_status(sub_id, "closed")
            db.update_opportunity_status(opp_id, "rejected")
            db.log_event("pr_closed", f"Closed (not merged): {pr_url}", opp_id)
            logger.info(f"PR closed (not merged): {pr_url}")
            stats["closed"] += 1

        elif status["state"] == "open":
            # Still open — normalise status field
            if sub.get("status") != "open":
                db.update_submission_status(sub_id, "open")

        elif status["state"] == "not_found":
            logger.warning(f"PR not found (deleted?): {pr_url}")
            db.update_submission_status(sub_id, "closed")
            db.update_opportunity_status(opp_id, "rejected")

    db.log_event(
        "monitor_complete",
        f"checked={stats['checked']} merged={stats['merged']} "
        f"closed={stats['closed']} errors={stats['errors']}",
    )
    logger.info(f"Monitor complete: {stats}")
    return stats


# ─── Scheduler hook ───────────────────────────────────────────────────────────

def start_scheduler(scheduler: AsyncIOScheduler, dry_run: bool = False):
    """Register monitor job on shared AsyncIOScheduler."""

    def _job():
        if dry_run:
            logger.info("[DRY RUN] Monitor: would check PR statuses")
            return
        run_monitor()

    scheduler.add_job(
        _job,
        "interval",
        minutes=MONITOR_INTERVAL_MINUTES,
        id="monitor",
        replace_existing=True,
    )
    logger.info(f"Monitor scheduled every {MONITOR_INTERVAL_MINUTES}min (dry_run={dry_run})")
