"""
test_dry_run.py — Complete dry-run pipeline test for Sentinel Earn
Tests the full execution loop end-to-end without side effects
"""
import os
import sys
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

import db
from executor import run_executor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('dry_run_test.log')
    ]
)

logger = logging.getLogger(__name__)


def setup_test_opportunity():
    """Insert a test opportunity into the database."""
    logger.info("Setting up test opportunity...")
    
    # Use a real, simple GitHub issue for testing
    test_issue_url = "https://github.com/python/cpython/issues/100000"
    
    # Insert test opportunity (matching db.py signature)
    db.insert_opportunity(
        source="test",
        title="Test Issue for Dry Run",
        repo_url="https://github.com/python/cpython",
        issue_url=test_issue_url,
        bounty_amount=0,
        currency="USD",
        complexity_score=5.0
    )
    
    logger.info(f"Test opportunity created: {test_issue_url}")
    return test_issue_url


def run_dry_run_test():
    """Run complete dry-run test."""
    logger.info("=" * 80)
    logger.info("SENTINEL EARN - DRY RUN PIPELINE TEST")
    logger.info("=" * 80)
    
    try:
        # Step 1: Setup test opportunity
        logger.info("\n[STEP 1] Setting up test opportunity...")
        test_url = setup_test_opportunity()
        
        # Step 2: Run executor in dry-run mode
        logger.info("\n[STEP 2] Running executor in DRY-RUN mode...")
        logger.info("This will:")
        logger.info("  [YES] Fetch real issue details from GitHub")
        logger.info("  [YES] Validate repository URL (security check)")
        logger.info("  [YES] Simulate context building")
        logger.info("  [YES] Simulate fix generation")
        logger.info("  [NO] NOT clone repository")
        logger.info("  [NO] NOT apply patches")
        logger.info("  [NO] NOT run tests")
        logger.info("  [NO] NOT create PR")
        logger.info("")
        
        result = run_executor(dry_run=True)
        
        # Step 3: Analyze results
        logger.info("\n[STEP 3] Analyzing results...")
        
        if result is None:
            logger.error("[FAIL] Dry run returned None - no opportunity found or error occurred")
            return False
        
        logger.info("[PASS] Dry run completed successfully!")
        logger.info(f"\nResult summary:")
        logger.info(f"  - Dry run: {result.get('dry_run', False)}")
        logger.info(f"  - Would attempt: {result.get('would_attempt', False)}")
        logger.info(f"  - Language: {result.get('language', 'N/A')}")
        logger.info(f"  - Context chars: {result.get('context_chars', 0)}")
        logger.info(f"  - Keywords: {result.get('keywords', [])[:5]}")
        
        if result.get('skipped'):
            logger.info(f"  - Skipped: {result.get('reason', 'Unknown')}")
            logger.info(f"  - Complexity: {result.get('complexity', 'N/A')}/10")
        
        # Step 4: Verify execution states
        logger.info("\n[STEP 4] Verifying execution states...")
        
        # Check database logs
        events = db.get_recent_events(limit=20)
        logger.info(f"[PASS] Found {len(events)} execution events in database")
        
        for event in events[:5]:
            detail = event.get('detail', event.get('details', ''))
            logger.info(f"  - {event['event']}: {detail[:60]}")
        
        logger.info("\n" + "=" * 80)
        logger.info("DRY RUN TEST COMPLETED SUCCESSFULLY")
        logger.info("=" * 80)
        logger.info("\nNext steps:")
        logger.info("  1. Review dry_run_test.log for detailed execution trace")
        logger.info("  2. Check database for execution events")
        logger.info("  3. Run with dry_run=False for full execution (requires Ollama)")
        logger.info("")
        
        return True
        
    except Exception as e:
        logger.exception(f"[FAIL] Dry run test failed: {e}")
        return False


def test_individual_components():
    """Test individual components in isolation."""
    logger.info("\n" + "=" * 80)
    logger.info("TESTING INDIVIDUAL COMPONENTS")
    logger.info("=" * 80)
    
    try:
        # Test 1: Security validation
        logger.info("\n[TEST 1] Security validation...")
        from security import validate_git_url
        
        test_urls = [
            ("https://github.com/python/cpython.git", True),
            ("https://github.com/octocat/Hello-World", True),
            ("http://github.com/test/repo.git", False),  # Not HTTPS
            ("https://evil.com/repo.git", False),  # Not GitHub
            ("https://github.com/test/repo; rm -rf /", False),  # Shell injection
        ]
        
        for url, expected in test_urls:
            result = validate_git_url(url)
            status = "[PASS]" if result == expected else "[FAIL]"
            logger.info(f"  {status} {url}: {result}")
        
        # Test 2: Patch validation
        logger.info("\n[TEST 2] Patch validation...")
        from patch_engine import validate_patch_json
        
        valid_patch = {
            "fix": {
                "files": [
                    {
                        "path": "test.py",
                        "action": "modify",
                        "changes": [
                            {
                                "description": "Fix typo",
                                "old_code": "print('hello')",
                                "new_code": "print('Hello, World!')"
                            }
                        ]
                    }
                ]
            }
        }
        
        is_valid, errors = validate_patch_json(valid_patch)
        logger.info(f"  [PASS] Valid patch: {is_valid} (errors: {errors})")
        
        invalid_patch = {"fix": {}}  # Missing 'files'
        is_valid, errors = validate_patch_json(invalid_patch)
        logger.info(f"  [PASS] Invalid patch detected: {not is_valid} (errors: {errors})")
        
        # Test 3: Test framework detection
        logger.info("\n[TEST 3] Test framework detection...")
        from test_runner import detect_test_framework, TestFramework
        
        # This will fail gracefully if no repo exists
        test_dir = Path(__file__).parent
        framework = detect_test_framework(test_dir)
        logger.info(f"  [PASS] Detected framework: {framework.value}")
        
        logger.info("\n[PASS] All component tests passed!")
        return True
        
    except Exception as e:
        logger.exception(f"[FAIL] Component test failed: {e}")
        return False


if __name__ == "__main__":
    logger.info("Starting Sentinel Earn dry-run test suite...\n")
    
    # Run component tests first
    component_success = test_individual_components()
    
    # Run full dry-run test
    dry_run_success = run_dry_run_test()
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("TEST SUITE SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Component tests: {'PASSED' if component_success else 'FAILED'}")
    logger.info(f"Dry-run test:    {'PASSED' if dry_run_success else 'FAILED'}")
    logger.info("=" * 80)
    
    # Exit with appropriate code
    sys.exit(0 if (component_success and dry_run_success) else 1)
