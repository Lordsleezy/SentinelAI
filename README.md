# SentinelAI

**Autonomous AI Operations Platform**

SentinelAI is a persistent, locally-running autonomous AI system designed to execute revenue-generating tasks, manage opportunities, and serve as the foundational runtime for the Sentinel ecosystem.

---

## 🎯 Vision

SentinelAI transforms your computer into an autonomous AI operations center that:
- Runs continuously in the background
- Scans for profitable opportunities
- Executes repairs and tasks autonomously
- Generates revenue through multiple streams
- Operates with human-in-the-loop approval gates
- Can be controlled remotely from anywhere

---

## 🚀 Current Capabilities

### Autonomous GitHub Repair
- Scans open-source repositories for fixable issues
- Analyzes code using AST-based context building
- Generates deterministic patches with local LLM (Ollama)
- Runs tests before and after patches
- Creates pull requests with detailed explanations
- Tracks earnings and success metrics

### Intelligent Execution
- **8 execution states**: DISCOVERED → ANALYZING → PATCHING → TESTING → VERIFYING → READY_TO_SUBMIT → FAILED → ROLLED_BACK
- **Security-first**: Multi-layer validation before any operations
- **Atomic operations**: Full rollback on any failure
- **Test verification**: Baseline + post-patch testing
- **Comprehensive logging**: Database + file + console

### Safety & Reliability
- Strict issue filtering (complexity ≤ 3, active repos, passing CI)
- Malicious code detection
- Path traversal prevention
- Resource limits on subprocesses
- Approval gates before execution and submission
- Execution telemetry tracking

---

## 📦 Installation

### Prerequisites
- Python 3.11+
- Git
- [Ollama](https://ollama.ai) with `qwen2.5-coder:14b` model
- GitHub personal access token

### Setup

```bash
# Clone repository
cd Desktop
# (Already renamed to SentinelAI)

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your GitHub token and username

# Initialize database
python -c "import db; db.init_db()"

# Pull Ollama model
ollama pull qwen2.5-coder:14b
```

---

## 🎮 Usage

### Dry-Run Test (Safe)
```bash
python test_dry_run.py
```
Tests the full pipeline without side effects.

### Live Test Mode (Real Execution)
```bash
# Scan for issues first
python live_test.py --scan-first

# Run with safety gates
python live_test.py

# Auto-approve (dangerous!)
python live_test.py --auto-approve
```

### Dashboard (Monitor Operations)
```bash
python dashboard.py
```
Opens web dashboard at `http://localhost:5000`

---

## 🏗️ Architecture

```
SentinelAI/
├── Core Modules
│   ├── executor.py          # Main execution pipeline
│   ├── scanner.py           # Opportunity discovery
│   ├── context_builder.py   # AST-based code analysis
│   ├── patch_engine.py      # Deterministic patching
│   ├── test_runner.py       # Test framework detection & execution
│   ├── git_operations.py    # Atomic git operations
│   └── security.py          # Security validation
│
├── Intelligence
│   ├── prompt_engine.py     # Ollama prompt engineering
│   ├── learning.py          # Success/failure memory
│   └── repo_analyzer.py     # Repository quality scoring
│
├── Infrastructure
│   ├── db.py                # SQLite database layer
│   ├── monitor.py           # System monitoring
│   └── dashboard.py         # Web UI
│
└── Testing
    ├── test_dry_run.py      # Dry-run pipeline test
    └── live_test.py         # Live execution with safety gates
```

---

## 🔄 Execution States

| State | Description |
|-------|-------------|
| `DISCOVERED` | Opportunity identified and queued |
| `ANALYZING` | Fetching issue details, building context |
| `PATCHING` | Generating and applying patches |
| `TESTING` | Running baseline and post-patch tests |
| `VERIFYING` | Validating test results and patch quality |
| `READY_TO_SUBMIT` | All checks passed, ready for PR |
| `FAILED` | Execution failed at any stage |
| `ROLLED_BACK` | Changes rolled back after failure |

---

## 📊 Database Schema

### Opportunities
Tracks discovered issues and their metadata.

### Submissions
Tracks pull requests and earnings.

### Agent Log
Comprehensive execution event logging.

---

## 🛡️ Security Features

- **URL validation** before cloning
- **Repository audit** after cloning (size, file count, malicious patterns)
- **Path traversal prevention**
- **Subprocess isolation** with resource limits
- **Dangerous pattern detection**
- **Atomic rollback** on any failure

---

## 🎯 Roadmap

### Phase 1: Complete Rebrand ✓ IN PROGRESS
- [x] Rename project to SentinelAI
- [x] Update database paths with migration
- [x] Update documentation
- [ ] Test renamed system

### Phase 2: Desktop Application
- [ ] Electron/Tauri desktop shell
- [ ] System tray icon
- [ ] Always-running background worker
- [ ] Start on boot option
- [ ] Live logs window
- [ ] Earnings dashboard

### Phase 3: Remote Control
- [ ] Secure REST API layer
- [ ] WebSocket live telemetry
- [ ] Mobile-friendly dashboard
- [ ] Push notifications
- [ ] Approval workflows

### Phase 4: OpenClaw Integration
- [ ] Personal assistant interface
- [ ] Voice command layer
- [ ] Phone/chat interface
- [ ] Command routing
- [ ] Task approvals

### Phase 5: Multi-Revenue Streams
- [ ] Dependency repair worker
- [ ] Website maintenance worker
- [ ] SEO repair worker
- [ ] Automated QA/testing worker
- [ ] CI/CD repair worker

### Phase 6: Learning System
- [ ] Successful patch memory
- [ ] Failed patch memory
- [ ] Maintainer behavior memory
- [ ] Repo trust scoring
- [ ] Profitability scoring

---

## 🤝 Contributing

SentinelAI is currently in active development. Contributions welcome!

---

## 📝 License

MIT License - See LICENSE file for details

---

## 🔗 Related Projects

- **Sentinel Web** - Web scraping and automation
- **Sentinel Guardian** - Security monitoring
- **Forge** - Development tools
- **OpenClaw** - Personal assistant layer

---

## 📞 Support

For issues, questions, or feature requests, please open an issue on GitHub.

---

**SentinelAI** - Autonomous AI Operations Platform  
*Built for reliability, designed for autonomy*
