# SentinelAI Deployment Checklist

**Version:** 1.0  
**Date:** May 26, 2026  
**Status:** Production-Ready for Controlled Deployment

---

## 📋 PRE-DEPLOYMENT CHECKLIST

### 1. System Requirements

- [ ] **Python 3.8+** installed
- [ ] **Ollama** installed and running (`ollama serve`)
- [ ] **Ollama Model** downloaded (`ollama pull qwen2.5-coder:14b`)
- [ ] **Git** installed and configured
- [ ] **Playwright** browsers installed (`playwright install`)
- [ ] **Sufficient RAM** (minimum 8GB, recommended 16GB+)
- [ ] **Sufficient Disk Space** (minimum 10GB free)

### 2. Dependencies Installation

```bash
cd SentinelAI
pip install -r requirements.txt
playwright install
```

- [ ] All Python dependencies installed
- [ ] Playwright browsers installed
- [ ] No import errors when running `python -c "import db, scanner, executor"`

### 3. Environment Configuration

- [ ] Copy `.env.example` to `.env`
- [ ] Set `GITHUB_TOKEN` (fine-grained PAT with repo access)
- [ ] Set `GITHUB_USERNAME`
- [ ] Generate and set `SENTINELAI_AUTH_TOKEN` (use: `python -c "import secrets; print(secrets.token_urlsafe(32))"`)
- [ ] Configure `OLLAMA_MODEL` (default: `qwen2.5-coder:14b`)
- [ ] Set `DRY_RUN=true` for initial testing
- [ ] Configure worker limits (`MAX_WORKERS`, `MAX_BROWSER_SESSIONS`, `MAX_AI_REQUESTS`)
- [ ] Configure monitoring intervals (`HEALTH_CHECK_INTERVAL`, `WATCHDOG_CHECK_INTERVAL`)

### 4. Database Initialization

```bash
python -c "import db; db.init_db()"
```

- [ ] Database created at `data/sentinel.db`
- [ ] All tables created successfully
- [ ] No database errors

### 5. System Validation

```bash
python test_final_system.py
```

- [ ] All 12 system tests pass
- [ ] No import errors
- [ ] No database errors
- [ ] No worker errors
- [ ] No queue errors

### 6. Stability Testing (Optional but Recommended)

```bash
python stability_test.py
```

- [ ] 5-minute stability test completes
- [ ] No memory leaks detected
- [ ] No excessive CPU usage
- [ ] No queue backups
- [ ] No task failures

---

## 🚀 DEPLOYMENT STEPS

### Step 1: Initial Dry-Run Test

1. [ ] Ensure `DRY_RUN=true` in `.env`
2. [ ] Start desktop app: `python desktop_app.py`
3. [ ] Verify dashboard loads at `http://localhost:5001`
4. [ ] Check system health at `/api/system/health`
5. [ ] Verify Ollama status shows "running"
6. [ ] Check all workers are idle
7. [ ] Verify watchdog is running
8. [ ] Verify health monitor is running

### Step 2: Test Remote Control (Optional)

1. [ ] Get your auth token from `.env`
2. [ ] Test status endpoint:
   ```bash
   curl http://localhost:5001/api/status
   ```
3. [ ] Test pause endpoint:
   ```bash
   curl -X POST http://localhost:5001/api/pause \
     -H "Authorization: Bearer YOUR_TOKEN"
   ```
4. [ ] Test resume endpoint:
   ```bash
   curl -X POST http://localhost:5001/api/resume \
     -H "Authorization: Bearer YOUR_TOKEN"
   ```
5. [ ] Verify emergency stop works

### Step 3: Test Scanner (Dry-Run)

1. [ ] Ensure `DRY_RUN=true`
2. [ ] Trigger manual scan via dashboard or API
3. [ ] Verify opportunities are discovered
4. [ ] Check complexity estimation
5. [ ] Verify scoring algorithm
6. [ ] Confirm no actual GitHub writes occur

### Step 4: Test Approval Flow

1. [ ] Find a pending opportunity in dashboard
2. [ ] Test approval via dashboard or API
3. [ ] Verify status changes to "approved"
4. [ ] Test rejection
5. [ ] Verify status changes to "rejected"

### Step 5: Enable Live Mode (CAUTION)

⚠️ **WARNING:** This enables actual GitHub operations!

1. [ ] Review all pending opportunities
2. [ ] Ensure you understand what will be submitted
3. [ ] Set `DRY_RUN=false` in `.env`
4. [ ] Restart desktop app
5. [ ] Monitor logs carefully
6. [ ] Be ready to use emergency stop if needed

### Step 6: Monitor Operations

1. [ ] Watch dashboard for active tasks
2. [ ] Monitor system health metrics
3. [ ] Check worker status regularly
4. [ ] Review queue depth
5. [ ] Monitor memory and CPU usage
6. [ ] Check logs for errors
7. [ ] Verify watchdog is recovering from failures

---

## 🔒 SECURITY CHECKLIST

### Authentication

- [ ] `SENTINELAI_AUTH_TOKEN` is strong and unique
- [ ] Token is not committed to version control
- [ ] Token is not shared publicly
- [ ] All sensitive endpoints require auth

### GitHub Access

- [ ] GitHub token has minimal required permissions
- [ ] Token is fine-grained (not classic PAT)
- [ ] Token is scoped to specific repositories if possible
- [ ] Token expiration is set appropriately

### Safety Constraints

- [ ] Approval gates are enabled
- [ ] No automatic PR submission without approval
- [ ] Rollback protection is active
- [ ] Emergency stop is functional
- [ ] Dry-run mode works correctly

### Network Security

- [ ] Desktop app only binds to localhost (not 0.0.0.0 in production)
- [ ] Firewall rules are configured if exposing remotely
- [ ] HTTPS is used if exposing to internet (not included by default)

---

## 📊 MONITORING CHECKLIST

### Health Monitoring

- [ ] CPU usage is reasonable (<50% average)
- [ ] RAM usage is stable (no memory leaks)
- [ ] Queue depth is manageable (<100 pending)
- [ ] Workers are healthy (heartbeats fresh)
- [ ] Watchdog is running and recovering failures

### Logging

- [ ] Logs are being written to console
- [ ] Error logs are visible
- [ ] Learning events are being recorded
- [ ] Recovery actions are logged

### Database

- [ ] Database file is being backed up regularly
- [ ] Database size is reasonable
- [ ] Old tasks are being cleaned up
- [ ] No database lock errors

---

## 🔄 BACKUP & RECOVERY

### Backup Procedures

- [ ] **Database Backup:**
  ```bash
  cp data/sentinel.db data/sentinel.db.backup.$(date +%Y%m%d)
  ```
- [ ] **Configuration Backup:**
  ```bash
  cp .env .env.backup
  ```
- [ ] Schedule regular backups (daily recommended)

### Recovery Procedures

- [ ] **Restore Database:**
  ```bash
  cp data/sentinel.db.backup.YYYYMMDD data/sentinel.db
  ```
- [ ] **Crash Recovery:**
  - System automatically recovers on restart
  - Running tasks are reset to pending
  - Workers are restarted
  - Watchdog resumes monitoring

### Emergency Procedures

- [ ] **Emergency Stop:**
  ```bash
  curl -X POST http://localhost:5001/api/emergency-stop \
    -H "Authorization: Bearer YOUR_TOKEN"
  ```
- [ ] **Pause All Workers:**
  ```bash
  curl -X POST http://localhost:5001/api/system/pause \
    -H "Authorization: Bearer YOUR_TOKEN"
  ```
- [ ] **Kill Process:**
  ```bash
  # Find process
  ps aux | grep desktop_app.py
  # Kill it
  kill -9 <PID>
  ```

---

## 🧪 POST-DEPLOYMENT VALIDATION

### First Hour

- [ ] Monitor dashboard continuously
- [ ] Check for any errors in logs
- [ ] Verify workers are processing tasks
- [ ] Confirm queue is not backing up
- [ ] Check memory usage is stable

### First Day

- [ ] Review all submitted PRs (if any)
- [ ] Check learning memory is updating
- [ ] Verify platform performance tracking
- [ ] Confirm no memory leaks
- [ ] Review watchdog recovery count

### First Week

- [ ] Analyze earnings (if any)
- [ ] Review success/failure rates
- [ ] Check complexity estimation accuracy
- [ ] Optimize scoring weights if needed
- [ ] Review and adjust worker limits

---

## 📈 SCALING CONSIDERATIONS

### Increasing Capacity

To handle more opportunities:

1. [ ] Increase `MAX_WORKERS` (default: 3)
2. [ ] Increase `MAX_BROWSER_SESSIONS` (default: 3)
3. [ ] Increase `MAX_AI_REQUESTS` (default: 2)
4. [ ] Monitor CPU and RAM usage
5. [ ] Ensure Ollama can handle load

### Performance Tuning

- [ ] Adjust `SCAN_INTERVAL_HOURS` (default: 2)
- [ ] Tune `TASK_TIMEOUT_MINUTES` (default: 30)
- [ ] Adjust `HEALTH_CHECK_INTERVAL` (default: 60s)
- [ ] Tune `WATCHDOG_CHECK_INTERVAL` (default: 30s)

---

## ⚠️ KNOWN LIMITATIONS

- [ ] Aware: No automatic worker scaling
- [ ] Aware: No log rotation (logs grow indefinitely)
- [ ] Aware: No automatic temp file cleanup
- [ ] Aware: Browser session limits not enforced
- [ ] Aware: AI request limits not enforced
- [ ] Aware: No built-in HTTPS support
- [ ] Aware: No multi-machine distribution

---

## 📞 TROUBLESHOOTING

### Common Issues

**Issue: Ollama not responding**
- [ ] Check Ollama is running: `ollama list`
- [ ] Restart Ollama: `ollama serve`
- [ ] Verify model is downloaded: `ollama pull qwen2.5-coder:14b`

**Issue: Workers not processing tasks**
- [ ] Check worker status: `curl http://localhost:5001/api/system/workers`
- [ ] Restart workers: `curl -X POST http://localhost:5001/api/system/restart-workers -H "Authorization: Bearer TOKEN"`
- [ ] Check logs for errors

**Issue: Queue backing up**
- [ ] Increase worker count
- [ ] Check for stalled tasks
- [ ] Review task timeout settings
- [ ] Check worker health

**Issue: High memory usage**
- [ ] Restart desktop app
- [ ] Reduce worker count
- [ ] Clean up old tasks: `python -c "import queue_manager as qm; qm.cleanup_old_tasks(days=7)"`

**Issue: Database locked**
- [ ] Close any other connections to database
- [ ] Restart desktop app
- [ ] Check for zombie processes

---

## ✅ DEPLOYMENT SIGN-OFF

- [ ] All pre-deployment checks completed
- [ ] All deployment steps executed
- [ ] All security measures in place
- [ ] Monitoring is active
- [ ] Backup procedures established
- [ ] Emergency procedures tested
- [ ] Team trained on operations

**Deployed By:** _______________  
**Date:** _______________  
**Environment:** [ ] Development [ ] Staging [ ] Production  
**Mode:** [ ] Dry-Run [ ] Live

---

## 📚 ADDITIONAL RESOURCES

- **Phase Reports:** See `PHASE_*_REPORT.md` files
- **Complete Context:** See `COMPLETE_CONTEXT_HANDOFF.md`
- **API Documentation:** See dashboard at `/api/*` endpoints
- **Test Scripts:** `test_final_system.py`, `stability_test.py`, `test_always_on.py`

---

*End of Deployment Checklist*
