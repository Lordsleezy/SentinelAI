# Ollama Agent Guide - SentinelAI Development

**Version:** 1.0.0  
**Date:** May 26, 2026  
**Purpose:** Critical onboarding guide for AI coding agents  
**Audience:** Future Ollama-powered development agents, distributed AI workforce

---

## 🎯 WELCOME TO SENTINELAI

You are joining a **production-ready autonomous AI operations platform** that has completed 8 development phases and passed comprehensive validation. Your role is to implement specific features while preserving the stable foundation that has been built.

**This document is CRITICAL.** Read it completely before making any code changes.

---

## 📖 PROJECT PURPOSE

### What is SentinelAI?

SentinelAI is an autonomous GitHub revenue generation platform that:
- Discovers paid issues across multiple platforms (GitHub, Algora, IssueHunt)
- Generates AI-powered solutions using local Ollama
- Submits pull requests with human approval
- Learns and improves over time
- Operates continuously with crash recovery

### Core Philosophy

**Safety First:** All autonomous actions require human approval  
**Modular Design:** Each system is independently testable  
**Graceful Degradation:** System continues despite component failures  
**State Persistence:** Queue and data survive crashes  
**Continuous Learning:** Platform improves from experience

---

## 🏗️ ARCHITECTURE OVERVIEW

### Current Working Systems (ALL TESTED ✅)

```
SentinelAI Platform
├── Core Systems
│   ├── Scanner - Multi-platform opportunity discovery
│   ├── Executor - AI solution generation (Ollama)
│   ├── Database - SQLite with 9 tables
│   └── Desktop App - Flask + System Tray
│
├── Phase 7 Systems (Always-On Operations)
│   ├── Queue Manager - Persistent task queue
│   ├── Worker Manager - Orchestration + health monitoring
│   ├── Watchdog - Auto-recovery system
│   └── Health Monitor - CPU/RAM/Queue metrics
│
├── Phase 6 Systems (Learning Memory)
│   ├── Platform Performance Tracking
│   ├── Issue Pattern Learning
│   ├── Complexity Feedback
│   └── Scoring Optimization
│
├── API Layer
│   ├── 30+ REST endpoints
│   ├── Token-based authentication
│   ├── Desktop dashboard
│   └── Mobile dashboard
│
└── Safety Layer (NEVER REMOVE)
    ├── Approval gates
    ├── Dry-run mode
    ├── Emergency stop
    ├── Rollback protection
    └── Security constraints
```

### Key Design Principles

1. **Modularity** - Each system is self-contained
2. **Testability** - All systems have test coverage
3. **Observability** - Comprehensive logging and monitoring
4. **Resilience** - Graceful error handling and recovery
5. **Safety** - Multiple layers of protection

---

## 🚨 CRITICAL CONSTRAINTS

### MUST PRESERVE (NEVER REMOVE OR MODIFY)

#### 1. Safety Systems ⚠️

```python
# NEVER remove or bypass these systems:
- Approval gates for all PR submissions
- Dry-run mode functionality
- Emergency stop capability
- Rollback protection
- Security constraint checks
```

**Why:** These prevent unauthorized or dangerous autonomous actions.

#### 2. Core Architecture 🏗️

```python
# NEVER remove or break these systems:
- Queue Manager (queue_manager.py)
- Worker Manager (worker_manager.py)
- Watchdog (watchdog.py)
- Health Monitor (health_monitor.py)
- Learning Memory (learning_memory.py)
```

**Why:** These enable crash recovery and continuous operation.

#### 3. Database Schema 💾

```python
# NEVER delete or rename these tables:
- opportunities
- submissions
- agent_log
- platform_performance
- issue_patterns
- complexity_feedback
- scoring_weights
- learning_events
- task_queue
```

**Why:** Breaking schema breaks backward compatibility and data integrity.

#### 4. API Endpoints 🌐

```python
# NEVER remove or change response formats:
- All 30+ existing endpoints
- Authentication requirements
- Response JSON structures
```

**Why:** External integrations and dashboards depend on these.

---

## ❌ FORBIDDEN ACTIONS

### NEVER DO THESE:

1. ❌ **Remove approval gates** - All PR submissions MUST require human approval
2. ❌ **Remove dry-run protections** - System must be testable without side effects
3. ❌ **Remove rollback systems** - Errors must be recoverable
4. ❌ **Remove watchdog monitoring** - System must auto-recover from crashes
5. ❌ **Remove health monitoring** - System must track its own health
6. ❌ **Remove learning memory** - System must improve over time
7. ❌ **Expose credentials** - Never log or expose tokens/passwords
8. ❌ **Add unrestricted autonomous behavior** - All external actions need approval
9. ❌ **Remove authentication** - API endpoints must remain protected
10. ❌ **Break backward compatibility** - Existing data/APIs must continue working

### NEVER DO THESE (Architecture):

11. ❌ **Massive refactors** - Make small, incremental changes
12. ❌ **Rewrite stable systems** - If it works, don't break it
13. ❌ **Remove error handling** - Graceful degradation is critical
14. ❌ **Remove logging** - Observability is essential
15. ❌ **Bypass safety checks** - Security constraints exist for a reason

---

## ✅ RECOMMENDED PRACTICES

### DO THESE:

1. ✅ **Read existing code first** - Understand before changing
2. ✅ **Make small, incremental changes** - Test each change
3. ✅ **Preserve existing functionality** - Add, don't replace
4. ✅ **Write tests** - Validate your changes work
5. ✅ **Document your changes** - Update docs and comments
6. ✅ **Follow existing patterns** - Maintain consistency
7. ✅ **Use git branches** - Protect the main branch
8. ✅ **Commit frequently** - Small, focused commits
9. ✅ **Test before committing** - Run validation tests
10. ✅ **Ask for clarification** - When in doubt, ask

---

## 🔄 DEVELOPMENT WORKFLOW

### Role Division

**Claude/Cline (Architecture & Debugging):**
- High-level architecture decisions
- Complex debugging and problem-solving
- System design and planning
- Integration of major components

**Ollama Agents (Implementation & Scaffolding):**
- Feature implementation
- Code scaffolding
- Incremental improvements
- Modular task completion
- Documentation updates

### Modular Task Workflow

1. **Receive Task** - Clear, scoped objective
2. **Read Context** - Review relevant docs and code
3. **Plan Approach** - Small, incremental steps
4. **Implement** - Write code following existing patterns
5. **Test** - Validate changes work
6. **Document** - Update docs and comments
7. **Commit** - Small, focused commit
8. **Report** - Summarize what was done

### Incremental Development

**Good Example:**
```
Task: Add new API endpoint
1. Create endpoint function
2. Add route to Flask app
3. Write tests
4. Update API documentation
5. Commit: "Add /api/new-endpoint"
```

**Bad Example:**
```
Task: Improve system
1. Rewrite entire backend
2. Change database schema
3. Remove old endpoints
4. Commit: "Major refactor"
```

---

## 📝 CODING STANDARDS

### Python Style

```python
# Follow existing patterns:
- PEP 8 style guide
- Type hints where helpful
- Docstrings for functions
- Clear variable names
- Comprehensive error handling

# Example:
def process_task(task_id: int) -> bool:
    """
    Process a task from the queue.
    
    Args:
        task_id: ID of the task to process
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Implementation
        return True
    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}")
        return False
```

### Error Handling

```python
# ALWAYS handle errors gracefully:
try:
    result = risky_operation()
except SpecificException as e:
    logger.error(f"Operation failed: {e}")
    # Graceful degradation
    return default_value
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    # Don't crash the system
    return None
```

### Logging

```python
# Use appropriate log levels:
logger.debug("Detailed debugging info")
logger.info("Normal operation info")
logger.warning("Something unexpected but handled")
logger.error("Error that needs attention")
logger.critical("System-level failure")

# NEVER log credentials:
logger.info(f"User: {username}")  # ✅ OK
logger.info(f"Token: {token}")    # ❌ FORBIDDEN
```

---

## 🧪 TESTING REQUIREMENTS

### Before Committing

**ALWAYS run these tests:**

```bash
# 1. Comprehensive validation
python test_final_system.py

# 2. Import validation
python -c "import db, scanner, executor, desktop_app"

# 3. Specific system tests (if modified)
python test_always_on.py      # Queue/Worker/Watchdog
python test_learning.py        # Learning memory
```

### Writing Tests

```python
# Add tests for new features:
def test_new_feature():
    """Test that new feature works correctly."""
    # Setup
    setup_test_environment()
    
    # Execute
    result = new_feature()
    
    # Validate
    assert result is not None
    assert result.status == "success"
    
    # Cleanup
    cleanup_test_environment()
```

---

## 📚 DOCUMENTATION REQUIREMENTS

### Update Documentation When:

1. **Adding new features** - Update README.md
2. **Adding new endpoints** - Update API docs
3. **Changing behavior** - Update relevant phase reports
4. **Adding new modules** - Add docstrings and comments
5. **Fixing bugs** - Document the fix

### Documentation Style

```markdown
# Clear, concise, actionable

## What it does
Brief description of functionality

## How to use it
Code examples and usage patterns

## Important notes
Warnings, constraints, dependencies
```

---

## 🔍 HOW TO WORK INCREMENTALLY

### Incremental Development Strategy

**Phase 1: Understand**
- Read existing code
- Review documentation
- Understand dependencies
- Identify integration points

**Phase 2: Plan**
- Break task into small steps
- Identify what NOT to change
- Plan testing approach
- Consider edge cases

**Phase 3: Implement**
- Make smallest possible change
- Test immediately
- Commit if successful
- Repeat for next small change

**Phase 4: Validate**
- Run all tests
- Check for regressions
- Verify documentation updated
- Review changes

**Phase 5: Commit**
- Small, focused commits
- Clear commit messages
- Push to branch (not main)
- Request review if needed

---

## 🛡️ SAFETY SYSTEMS EXPLAINED

### Why Safety Systems Matter

SentinelAI operates autonomously and interacts with external systems (GitHub). Without safety systems, it could:
- Submit unauthorized PRs
- Expose credentials
- Make irreversible changes
- Cause financial/reputational damage

### Approval Gates

```python
# All PR submissions go through approval:
if opportunity.status == "approved":
    submit_pr()  # ✅ Safe
else:
    queue_for_approval()  # ✅ Safe
    
# NEVER bypass approval:
submit_pr()  # ❌ FORBIDDEN without approval check
```

### Dry-Run Mode

```python
# Dry-run prevents actual external actions:
if os.getenv("DRY_RUN") == "true":
    logger.info("DRY RUN: Would submit PR")
    return mock_response()
else:
    return github.create_pull_request()
```

### Emergency Stop

```python
# Emergency stop halts all operations:
@app.route('/api/emergency-stop', methods=['POST'])
def emergency_stop():
    global EMERGENCY_STOP
    EMERGENCY_STOP = True
    stop_all_workers()
    return {"status": "stopped"}
```

---

## 🎯 COMMON TASKS & PATTERNS

### Adding a New API Endpoint

```python
# 1. Add route to desktop_app.py
@app.route('/api/new-endpoint', methods=['GET'])
@require_auth  # Always require auth
def new_endpoint():
    try:
        result = get_data()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Endpoint failed: {e}")
        return jsonify({"error": str(e)}), 500

# 2. Add tests
# 3. Update API documentation
# 4. Commit
```

### Adding a New Database Table

```python
# 1. Add table creation in db.py init_db()
cursor.execute('''
    CREATE TABLE IF NOT EXISTS new_table (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        data TEXT
    )
''')

# 2. Add helper functions
def insert_new_table_data(data):
    # Implementation
    pass

# 3. Update schema documentation
# 4. Test migration
# 5. Commit
```

### Adding a New Worker Type

```python
# 1. Define handler function
def new_worker_handler(task):
    try:
        # Process task
        return True
    except Exception as e:
        logger.error(f"Worker failed: {e}")
        return False

# 2. Register handler
manager.register_handler("new_worker", new_worker_handler)

# 3. Create worker
worker = manager.create_worker("new_worker_1", ["new_worker"])
worker.start()

# 4. Test thoroughly
# 5. Commit
```

---

## 📖 REQUIRED READING

### Before Starting ANY Work

1. **MASTER_HANDOFF.md** - Complete overview
2. **OLLAMA_AGENT_GUIDE.md** - This document
3. **CURRENT_SYSTEM_STATE.md** - What exists now
4. **NEXT_SESSION_BOOTSTRAP.md** - Current priorities

### Before Specific Tasks

**Electron Development:**
- ELECTRON_IMPLEMENTATION_PLAN.md
- BACKEND_INTEGRATION_PLAN.md

**UI Work:**
- UI_VISION.md
- templates/desktop_dashboard.html

**Backend Changes:**
- CURRENT_SYSTEM_STATE.md
- Relevant phase reports

---

## 🚦 COMMIT DISCIPLINE

### Good Commit Messages

```
✅ Add health monitoring endpoint
✅ Fix queue overflow bug
✅ Update learning memory documentation
✅ Implement worker auto-restart
```

### Bad Commit Messages

```
❌ Update stuff
❌ Fix things
❌ WIP
❌ Changes
```

### Commit Frequency

- **Too frequent:** Every line change
- **Too infrequent:** Massive changes
- **Just right:** Logical, testable units

### Branch Strategy

```bash
# Create feature branch
git checkout -b feature/new-endpoint

# Make changes, test, commit
git add .
git commit -m "Add new endpoint"

# Push to branch
git push origin feature/new-endpoint

# Merge after review
```

---

## 🎓 LEARNING FROM THE CODEBASE

### Study These Examples

**Good Error Handling:**
- `watchdog.py` - Graceful recovery
- `worker_manager.py` - Health monitoring

**Good Modularity:**
- `queue_manager.py` - Self-contained system
- `learning_memory.py` - Independent learning

**Good Testing:**
- `test_final_system.py` - Comprehensive validation
- `test_always_on.py` - System integration

**Good Documentation:**
- `FINAL_SENTINELAI_BUILD_REPORT.md` - Complete docs
- Phase reports - Detailed implementation

---

## 🔧 TROUBLESHOOTING

### Common Issues

**Import Errors:**
```bash
# Check Python path
python -c "import sys; print(sys.path)"

# Verify all modules import
python -c "import db, scanner, executor"
```

**Database Errors:**
```bash
# Reinitialize database
python -c "import db; db.init_db()"
```

**Worker Issues:**
```bash
# Check worker status
curl http://localhost:5001/api/system/workers
```

**Test Failures:**
```bash
# Run specific test
python test_final_system.py

# Check logs
tail -f logs/sentinel.log
```

---

## 🎯 YOUR FIRST TASK

### Recommended First Task

**Goal:** Get familiar with the codebase

**Steps:**
1. Read MASTER_HANDOFF.md
2. Read this document completely
3. Read CURRENT_SYSTEM_STATE.md
4. Run `python test_final_system.py`
5. Explore the codebase
6. Make a small documentation improvement
7. Commit and push

**This builds confidence without risk.**

---

## 🤝 COLLABORATION EXPECTATIONS

### Working with Other Agents

- **Communicate clearly** - Document what you're working on
- **Avoid conflicts** - Don't modify same files simultaneously
- **Review each other** - Check commits for issues
- **Share learnings** - Document patterns and solutions

### Working with Humans

- **Ask questions** - When unclear, ask
- **Provide context** - Explain your changes
- **Accept feedback** - Iterate based on review
- **Document decisions** - Record why choices were made

---

## 📋 CHECKLIST FOR EVERY TASK

Before starting:
- [ ] Read task description completely
- [ ] Review relevant documentation
- [ ] Understand what NOT to change
- [ ] Plan incremental approach

During implementation:
- [ ] Make small changes
- [ ] Test frequently
- [ ] Follow existing patterns
- [ ] Handle errors gracefully
- [ ] Add logging where appropriate

Before committing:
- [ ] Run all tests
- [ ] Check for regressions
- [ ] Update documentation
- [ ] Review changes
- [ ] Write clear commit message

After committing:
- [ ] Push to branch
- [ ] Verify CI passes (if applicable)
- [ ] Request review if needed
- [ ] Monitor for issues

---

## 🎉 CONCLUSION

You are now ready to contribute to SentinelAI. Remember:

**Key Principles:**
1. **Safety First** - Never compromise safety systems
2. **Incremental Changes** - Small, testable improvements
3. **Preserve Stability** - Don't break what works
4. **Test Thoroughly** - Validate all changes
5. **Document Everything** - Help future developers

**When in Doubt:**
- Read the documentation
- Study existing code
- Ask for clarification
- Make smaller changes
- Test more thoroughly

**You are part of building a production-ready autonomous AI operations platform. Your careful, incremental work ensures the platform remains stable, safe, and continuously improving.**

---

**Welcome to the team!** 🚀

---

*End of Ollama Agent Guide*

**SentinelAI v1.0.0** - Production-Ready Autonomous AI Operations Platform
