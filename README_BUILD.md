# SentinelAI - Distribution Build Guide

## Quick Start (Windows)

### Prerequisites
- Python 3.8+
- Node.js 16+ (with npm)
- Git
- 10GB free disk space

### Build Steps

1. **Clone and setup**
   ```bash
   git clone https://github.com/sentinelprime/sentinelai.git
   cd sentinelai
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   npm install --save-dev electron-builder pyinstaller
   ```

2. **Build installer** (all-in-one)
   ```bash
   scripts\build_installer.bat
   ```
   Output: `installer_dist\SentinelAI Setup.exe`

3. **Or build steps separately**
   ```bash
   scripts\build_backend.bat          # Creates sentinel_backend.exe
   node create_icon.js                # Creates icon
   cd desktop-shell && npm run dist   # Creates installer
   ```

## Architecture

### Orchestration Pipeline (Tracks 17-25)
- **Task Decomposition** — Breaks complex requests into subtasks
- **Confidence Escalation** — Ollama → Claude API on low confidence
- **Self-Verification** — Validates outputs with retry logic
- **Chain of Thought** — Reasoning scaffolds for code tasks
- **RAG** — Semantic search over codebase (ChromaDB)
- **Model Routing** — Intelligent model selection
- **Structured Output** — JSON schema enforcement
- **Plan Approval** — User review modal for complex tasks
- **Full Pipeline** — Coordinates all components

### Tier System (Part 0)
- **Free Tier** — Core features with limits
  - 10 Forge tasks
  - 20 web searches
  - Limited earn results (HackerOne + RemoteOK only)
- **Pro Tier** — Unlimited everything
  - All features unlocked
  - No limits
  - Home Assistant, cameras, messaging, etc.

### Build System (Parts 1-7)
- **Part 1** — Repo cleanup (venv/node_modules included)
- **Part 2** — Setup wizard (9-page first-run config)
- **Part 3** — PyInstaller backend bundling
- **Part 4** — Electron Builder NSIS installer
- **Part 5** — GitHub Actions CI/CD
- **Part 6** — Capability system (self-extending)
- **Part 7** — Final polish and distribution

## Features

### Core
- ✅ Intelligent task orchestration
- ✅ Local AI (Ollama) + cloud fallback (Claude)
- ✅ RAG codebase context
- ✅ Plan approval before execution
- ✅ License-based tier enforcement

### Integrations
- **Code** — Forge (code generation + repair)
- **Web** — Brave search, OpenClaw
- **Calendar** — Google Calendar integration
- **Notes** — Full-text searchable vault
- **Smart Home** — Home Assistant, cameras
- **Messaging** — Telegram, WhatsApp bridges
- **Finance** — Firefly III, market data
- **Music** — Spotify control
- **Health** — Wearables, Miniflux
- **Earn** — HackerOne, RemoteOK, Upwork scanning
- **Market** — OpenBB, Freqtrade
- **Package** — USPS tracking

## Installation

1. Download `SentinelAI Setup.exe`
2. Run installer
3. Follow 9-page setup wizard
4. (Optional) Activate Pro license
5. Launch SentinelAI

**System Requirements:**
- Windows 10 or later
- 4GB RAM minimum
- 5GB free disk space
- Internet connection (for setup wizard)

## Configuration

All configuration via first-run setup wizard or `.env` file:

```bash
# AI & APIs
ANTHROPIC_API_KEY=sk_live_...
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5-coder:14b

# GitHub (for code submission)
GITHUB_TOKEN=ghp_...
GITHUB_USERNAME=your-username

# Integrations
TELEGRAM_BOT_TOKEN=123456789:ABCDEF...
SPOTIFY_CLIENT_ID=abc123...
HA_TOKEN=eyJ0...

# License
LICENSE_FILE_PATH=~/.sentinelai/license.json
```

## Development

### Running from source
```bash
# Terminal 1: Backend
venv\Scripts\activate
python desktop_app.py

# Terminal 2: Electron
cd desktop-shell
npm start
```

### Testing
```bash
# Test orchestration pipeline
curl -X POST http://127.0.0.1:5001/orchestration/test

# Check license status
curl http://127.0.0.1:5001/license/status

# List capabilities
curl http://127.0.0.1:5001/capability/list
```

## License

- **Free** — Core features with usage limits
- **Pro** — $199/year for unlimited features
- Activate: Settings → "Activate License Key"

## Support

- GitHub Issues: https://github.com/sentinelprime/sentinelai/issues
- Website: https://sentinelprime.org
- Contact: support@sentinelprime.org

## Troubleshooting

### Backend won't start
- Check Python version: `python --version` (3.8+ required)
- Check Ollama running: `curl http://127.0.0.1:11434/api/tags`
- Check port 5001 free: `netstat -ano | findstr :5001`

### Installer fails
- Check disk space: 5GB minimum free
- Run as Administrator
- Disable antivirus temporarily

### Features blocked as "Pro required"
- Activate license key in settings
- Or switch to Pro tier at sentinelprime.org/pricing

## Architecture Diagram

```
┌─────────────────────────────────────┐
│       Windows Installer (.exe)      │
│  (SentinelAI Setup.exe ~500MB-1GB)  │
└──────────────┬──────────────────────┘
               │
        ┌──────┴──────┐
        ▼             ▼
    [Backend]    [Electron]
    Python       Node.js +
    Flask        React 3D
    SQLite       
        │             │
        │        ┌────┴────┐
        │        ▼         ▼
        │      Orb UI   Worker
        │      (Chat)   (Code)
        │
        └─► Orchestration
            Pipeline
                │
        ┌───────┼───────┐
        ▼       ▼       ▼
    Ollama  Claude   RAG
    Local   Cloud    Search
    
        │
        └─► 50+ Workers
            (Forge, OpenClaw,
             Home, Finance,
             Health, etc)
```

## Build Output

```
SentinelAI Setup.exe (~600MB-1GB)
├─ Electron shell
├─ Python backend (sentinel_backend.exe)
└─ All dependencies bundled
    ├─ Flask + Flask-CORS
    ├─ SQLAlchemy + SQLite
    ├─ ChromaDB + sentence-transformers
    ├─ Ollama client
    ├─ Anthropic SDK
    └─ 50+ worker modules
```

## Next Steps

1. ✅ Download installer from releases
2. ✅ Install (Windows 10+)
3. ✅ Run setup wizard
4. ✅ Activate Pro (optional)
5. ✅ Start using SentinelAI!

---

**Version:** 1.0.0-alpha  
**Release Date:** May 2026  
**Status:** Ready for distribution
