"""
main.py — Entry point for Sentinel Earn
APScheduler + FastAPI + CLI flags

Usage:
  python main.py                  Full agent (scan + execute + dashboard)
  python main.py --dry-run        Safe mode — no GitHub writes, no file changes
  python main.py --scan-now       Single scan then exit
  python main.py --execute-now    Single executor run then exit
  python main.py --dashboard-only Dashboard only (no automation)
"""
import asyncio
import argparse
import logging
import os
import sys
from datetime import datetime

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

load_dotenv()

DRY_RUN = os.getenv("DRY_RUN", "false").lower() in ("true", "1", "yes")

# ─── Logging ─────────────────────────────────────────────────────────────────

# Force UTF-8 on Windows stdout so log messages with Unicode don't crash
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
_file_handler = logging.FileHandler("sentinel_earn.log", encoding="utf-8")
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))
logging.basicConfig(level=logging.INFO, handlers=[_stream_handler, _file_handler])
logger = logging.getLogger("main")

# Quiet noisy libraries
for noisy in ("httpx", "httpcore", "playwright", "git", "apscheduler.scheduler"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Sentinel Earn — Autonomous Bounty Hunting Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--dry-run",        action="store_true", help="Safe mode — zero GitHub calls")
    p.add_argument("--scan-now",       action="store_true", help="Run one scan and exit")
    p.add_argument("--execute-now",    action="store_true", help="Run executor once and exit")
    p.add_argument("--dashboard-only", action="store_true", help="Dashboard only, no scheduling")
    p.add_argument("--port",           type=int, default=8765, help="Dashboard port (default 8765)")
    return p.parse_args()


# ─── One-shot helpers ─────────────────────────────────────────────────────────

async def _scan_once(dry_run: bool):
    from scanner import run_scan
    logger.info("Running single scan…")
    count = await run_scan(dry_run=dry_run)
    logger.info(f"Scan complete — {count} new opportunities added")


def _execute_once(dry_run: bool):
    from executor import run_executor
    logger.info("Running executor once…")
    result = run_executor(dry_run=dry_run)
    logger.info(f"Executor result: {result}")


# ─── Full agent ───────────────────────────────────────────────────────────────

async def _run_full_agent(dry_run: bool, port: int):
    import db
    import scanner
    import monitor
    from dashboard import app as dash_app

    logger.info("=" * 60)
    logger.info("  Sentinel Earn — Autonomous Bounty Hunting Agent")
    logger.info(f"  Dashboard : http://localhost:{port}")
    logger.info(f"  Dry run   : {dry_run}")
    logger.info(f"  DB        : {db.DB_PATH}")
    logger.info("=" * 60)

    db.init_db()
    db.log_event("agent_start", f"Sentinel Earn started. dry_run={dry_run}")

    scheduler = AsyncIOScheduler(timezone="UTC")
    scanner.start_scheduler(scheduler, dry_run=dry_run)
    monitor.start_scheduler(scheduler, dry_run=dry_run)
    scheduler.start()
    logger.info("Scheduler started")

    config = uvicorn.Config(
        dash_app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    await server.serve()


# ─── Dashboard-only ──────────────────────────────────────────────────────────

async def _run_dashboard_only(port: int):
    import db
    from dashboard import app as dash_app

    db.init_db()
    logger.info(f"Dashboard-only mode at http://localhost:{port}")

    config = uvicorn.Config(
        dash_app,
        host="0.0.0.0",
        port=port,
        log_level="warning",
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    await server.serve()


# ─── Entrypoint ───────────────────────────────────────────────────────────────

def main():
    args = _parse_args()
    dry_run = args.dry_run or DRY_RUN

    if dry_run:
        logger.info("=" * 42)
        logger.info("  DRY RUN MODE -- zero side effects")
        logger.info("  No GitHub calls, no file writes")
        logger.info("=" * 42)

    # Ensure DB exists for all modes
    import db
    db.init_db()
    logger.info(f"Database ready: {db.DB_PATH}")

    if args.scan_now:
        asyncio.run(_scan_once(dry_run))

    elif args.execute_now:
        _execute_once(dry_run)

    elif args.dashboard_only:
        asyncio.run(_run_dashboard_only(args.port))

    else:
        asyncio.run(_run_full_agent(dry_run, args.port))


if __name__ == "__main__":
    main()
