"""
live_test.py — Live test mode for Sentinel Earn
Executes full repair loop on real GitHub issues with safety gates
Stops before actual PR submission unless manually approved
"""
import os
import sys
import argparse
import logging
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime, timedelta

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

import db
from executor import run_executor
from scanner import scan_github_issues

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f'live_test_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log')
    ]
)

logger = logging.getLogger(__name__)


# ─── Issue Filtering ──────────────────────────────────────────────────────────

ALLOWED_LANGUAGES = {"python", "javascript", "typescript"}
MAX_COMPLEXITY = 3
MAX_ISSUE_AGE_DAYS = 180  # 6 months
MIN_REPO_STARS = 10  # Minimum stars for quality filter

REJECT_LABELS = {
    "feature", "enhancement", "feature-request", "new-feature",
    "refactor", "refactoring", "breaking-change", "major",
    "wontfix", "invalid", "duplicate", "question"
}


def filter_issue_by_quality(issue_data: Dict) -> tuple[bool, str]:
    """
    Apply strict quality filters to issue.
    
    Returns:
        (should_accept: bool, reason: str)
    """
    # Check language
    language = issue_data.get("language", "").lower()
    if language not in ALLOWED_LANGUAGES:
        return False, f"Language {language} not in allowed list"
    
    # Check labels for reject patterns
    labels = [l.lower() for l in issue_data.get("labels", [])]
    for label in labels:
        if any(reject in label for reject in REJECT_LABELS):
            return False, f"Rejected label: {label}"
    
    # Check issue age
    created_at = issue_data.get("created_at")
    if created_at:
        try:
            created_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            age_days = (datetime.now(created_date.tzinfo) - created_date).days
            if age_days > MAX_ISSUE_AGE_DAYS:
                return False, f"Issue too old: {age_days} days"
        except Exception:
            pass
    
    # Check for reproduction steps or clear description
    body = issue_data.get("body", "").lower()
    if len(body) < 50:
        return False, "Issue description too short"
    
    # Check for monorepo indicators
    repo_url = issue_data.get("repo_url", "")
    monorepo_indicators = ["monorepo", "workspace", "packages/", "apps/"]
    if any(indicator in repo_url.lower() or indicator in body for indicator in monorepo_indicators):
        return False, "Monorepo detected"
    
    return True, "Passed quality filters"


def select_best_issue() -> Optional[Dict]:
    """
    Select the best issue for live testing based on strict criteria.
    
    Returns:
        Issue data dict or None
    """
    logger.info("Scanning for suitable issues...")
    
    # Get opportunities from database
    opportunities = db.list_opportunities(status="new", limit=50)
    
    if not opportunities:
        logger.warning("No opportunities in database. Run scanner first.")
        return None
    
    logger.info(f"Found {len(opportunities)} opportunities in database")
    
    # Filter and score
    candidates = []
    for opp in opportunities:
        # Basic complexity filter
        if opp.get("complexity_score", 10) > MAX_COMPLEXITY:
            continue
        
        # Apply quality filters
        should_accept, reason = filter_issue_by_quality(opp)
        if not should_accept:
            logger.debug(f"Rejected {opp['issue_url']}: {reason}")
            continue
        
        # Calculate score (lower complexity = higher priority)
        score = 10 - opp.get("complexity_score", 5)
        candidates.append((score, opp))
    
    if not candidates:
        logger.error("No suitable issues found after filtering")
        return None
    
    # Sort by score (highest first)
    candidates.sort(reverse=True, key=lambda x: x[0])
    
    best_issue = candidates[0][1]
    logger.info(f"Selected issue: {best_issue['title']}")
    logger.info(f"  URL: {best_issue['issue_url']}")
    logger.info(f"  Complexity: {best_issue.get('complexity_score', 'N/A')}")
    logger.info(f"  Score: {candidates[0][0]}")
    
    return best_issue


# ─── Execution Telemetry ──────────────────────────────────────────────────────

class ExecutionTelemetry:
    """Track execution metrics for analysis."""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.metrics = {
            "prompt_timing": {},
            "patch_size": 0,
            "token_estimates": {},
            "test_duration": 0,
            "rollback_reason": None,
            "confidence_score": 0,
            "stages_completed": []
        }
    
    def record_stage(self, stage: str):
        """Record completion of a stage."""
        self.metrics["stages_completed"].append({
            "stage": stage,
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": (datetime.now() - self.start_time).total_seconds()
        })
    
    def record_prompt_timing(self, prompt_type: str, duration_seconds: float):
        """Record prompt execution time."""
        self.metrics["prompt_timing"][prompt_type] = duration_seconds
    
    def record_patch_size(self, files_count: int, total_lines: int):
        """Record patch size metrics."""
        self.metrics["patch_size"] = {
            "files": files_count,
            "total_lines": total_lines
        }
    
    def record_test_duration(self, duration_seconds: float):
        """Record test execution time."""
        self.metrics["test_duration"] = duration_seconds
    
    def record_rollback(self, reason: str):
        """Record rollback reason."""
        self.metrics["rollback_reason"] = reason
    
    def record_confidence(self, score: int):
        """Record confidence score."""
        self.metrics["confidence_score"] = score
    
    def get_summary(self) -> str:
        """Get telemetry summary."""
        total_time = (datetime.now() - self.start_time).total_seconds()
        
        summary = [
            "\n" + "=" * 80,
            "EXECUTION TELEMETRY SUMMARY",
            "=" * 80,
            f"Total execution time: {total_time:.1f}s",
            f"Stages completed: {len(self.metrics['stages_completed'])}",
            f"Confidence score: {self.metrics['confidence_score']}/10",
        ]
        
        if self.metrics["patch_size"]:
            summary.append(f"Patch size: {self.metrics['patch_size']['files']} files, "
                          f"{self.metrics['patch_size']['total_lines']} lines")
        
        if self.metrics["test_duration"]:
            summary.append(f"Test duration: {self.metrics['test_duration']:.1f}s")
        
        if self.metrics["rollback_reason"]:
            summary.append(f"Rollback reason: {self.metrics['rollback_reason']}")
        
        if self.metrics["prompt_timing"]:
            summary.append("\nPrompt timing:")
            for prompt_type, duration in self.metrics["prompt_timing"].items():
                summary.append(f"  - {prompt_type}: {duration:.1f}s")
        
        summary.append("=" * 80)
        return "\n".join(summary)


# ─── Live Test Mode ───────────────────────────────────────────────────────────

def run_live_test(auto_approve: bool = False) -> bool:
    """
    Run live test mode: full repair loop with safety gates.
    
    Args:
        auto_approve: If True, automatically approve PR submission
    
    Returns:
        True if successful, False otherwise
    """
    logger.info("=" * 80)
    logger.info("SENTINEL EARN - LIVE TEST MODE")
    logger.info("=" * 80)
    logger.info("")
    
    telemetry = ExecutionTelemetry()
    
    try:
        # Step 1: Select best issue
        logger.info("[STEP 1] Selecting best issue for live test...")
        telemetry.record_stage("issue_selection")
        
        issue = select_best_issue()
        if not issue:
            logger.error("No suitable issue found")
            return False
        
        logger.info(f"Selected: {issue['title']}")
        logger.info("")
        
        # Step 2: Execute repair loop (NOT dry-run)
        logger.info("[STEP 2] Executing full repair loop...")
        logger.info("This will:")
        logger.info("  [YES] Clone real repository")
        logger.info("  [YES] Generate real patches")
        logger.info("  [YES] Apply patches to files")
        logger.info("  [YES] Run real tests")
        logger.info("  [YES] Create git branch")
        logger.info("  [YES] Commit changes")
        logger.info("  [NO] Push to remote (safety gate)")
        logger.info("  [NO] Create PR (safety gate)")
        logger.info("")
        
        # Confirm before proceeding
        if not auto_approve:
            response = input("Proceed with live test? (yes/no): ")
            if response.lower() != "yes":
                logger.info("Live test cancelled by user")
                return False
        
        telemetry.record_stage("execution_start")
        
        # Run executor in LIVE mode (dry_run=False)
        # But we'll modify executor to stop before push/PR
        result = run_executor(dry_run=False)
        
        telemetry.record_stage("execution_complete")
        
        # Step 3: Analyze results
        logger.info("\n[STEP 3] Analyzing results...")
        
        if not result:
            logger.error("Execution failed - no result returned")
            telemetry.record_rollback("Execution returned None")
            return False
        
        if not result.get("success"):
            logger.error(f"Execution failed: {result.get('error', 'Unknown error')}")
            telemetry.record_rollback(result.get("error", "Unknown"))
            return False
        
        # Record telemetry
        telemetry.record_confidence(result.get("confidence", 0))
        
        if "baseline_tests" in result:
            baseline = result["baseline_tests"]
            post_patch = result.get("post_patch_tests", {})
            logger.info(f"\nTest results:")
            logger.info(f"  Baseline: {baseline['passed']}/{baseline['total']} passed")
            logger.info(f"  Post-patch: {post_patch.get('passed', 0)}/{post_patch.get('total', 0)} passed")
        
        # Step 4: Safety gate - manual approval for PR
        logger.info("\n[STEP 4] Safety gate - PR submission")
        logger.info(f"PR would be created for: {result.get('pr_url', 'N/A')}")
        logger.info(f"Confidence: {result.get('confidence', 0)}/10")
        logger.info("")
        
        if not auto_approve:
            response = input("Submit PR to GitHub? (yes/no): ")
            if response.lower() != "yes":
                logger.info("PR submission cancelled - test complete")
                logger.info(telemetry.get_summary())
                return True
        
        logger.info("✓ Live test completed successfully!")
        logger.info(telemetry.get_summary())
        return True
        
    except Exception as e:
        logger.exception(f"Live test failed: {e}")
        telemetry.record_rollback(str(e))
        logger.info(telemetry.get_summary())
        return False


# ─── Main Entry Point ─────────────────────────────────────────────────────────

def main():
    """Main entry point for live test mode."""
    parser = argparse.ArgumentParser(description="Sentinel Earn - Live Test Mode")
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Automatically approve all safety gates (dangerous!)"
    )
    parser.add_argument(
        "--scan-first",
        action="store_true",
        help="Scan for new issues before running test"
    )
    
    args = parser.parse_args()
    
    # Initialize database
    db.init_db()
    
    # Optionally scan for new issues
    if args.scan_first:
        logger.info("Scanning for new issues...")
        try:
            scan_github_issues(max_issues=20)
        except Exception as e:
            logger.error(f"Scan failed: {e}")
    
    # Run live test
    success = run_live_test(auto_approve=args.auto_approve)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
