# SentinelAI Rebrand Plan

**Status:** In Progress  
**Date:** May 26, 2026

---

## Phase 1: Complete Rebrand ✓ STARTED

### Directory Structure ✓
- [x] Renamed `SentinelEarn` → `SentinelAI`

### Files to Update

#### Python Files (Code Changes)
- [ ] `db.py` - Update DB_PATH, table names, function names
- [ ] `executor.py` - Update logger names, workspace paths
- [ ] `scanner.py` - Update references
- [ ] `dashboard.py` - Update UI labels, titles
- [ ] `main.py` - Update CLI references
- [ ] `monitor.py` - Update monitoring labels
- [ ] `live_test.py` - Update logging, telemetry names
- [ ] `test_dry_run.py` - Update test names
- [ ] All other `.py` files - Search/replace references

#### Database
- [ ] Rename `data/sentinel_earn.db` → `data/sentinelai.db`
- [ ] Update schema if needed
- [ ] Create migration script

#### Documentation
- [ ] `README.md` - Complete rewrite for SentinelAI
- [ ] `INTEGRATION_REPORT.md` - Update references
- [ ] `FINAL_UPGRADE_REPORT.md` - Update references
- [ ] `BUILD_REPORT.md` - Update references
- [ ] `AUDIT_REPORT.md` - Update references

#### Configuration
- [ ] `.env.example` - Update variable names
- [ ] `requirements.txt` - Update if needed
- [ ] `setup.sh` - Update references
- [ ] `setup.ps1` - Update references
- [ ] `Makefile` - Update targets

#### Logs
- [ ] Rename `sentinel_earn.log` → `sentinelai.log`
- [ ] Update logging configuration

---

## Search/Replace Strategy

### Global Replacements
1. `Sentinel Earn` → `SentinelAI`
2. `sentinel_earn` → `sentinelai`
3. `SentinelEarn` → `SentinelAI`
4. `SENTINEL_EARN` → `SENTINELAI`

### Careful Replacements (context-dependent)
- Database table names
- API endpoints
- Environment variables
- File paths
- Import statements

---

## Testing Checklist

After rebrand:
- [ ] Run `python test_dry_run.py`
- [ ] Run `python live_test.py --help`
- [ ] Check database connectivity
- [ ] Verify all imports work
- [ ] Test executor dry-run
- [ ] Verify logging works
- [ ] Check dashboard loads

---

## Backward Compatibility

Keep these for migration:
- Accept both old and new env var names
- Support both database paths temporarily
- Log migration warnings

---

## Next Steps After Rebrand

1. Update README with SentinelAI vision
2. Create ARCHITECTURE.md
3. Plan Phase 2: Desktop Application
4. Plan Phase 3: API Layer
5. Plan Phase 4: OpenClaw Integration
