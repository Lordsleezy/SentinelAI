# SentinelAI Overhaul - Completion Guide

## What's Been Completed (Tracks 1-4)

✅ **TRACK 1:** Orb UI - Dual window architecture, React orb with Three.js, worker windows  
✅ **TRACK 2:** Monaco Editor - Integrated into Forge window with dark theme  
✅ **TRACK 3:** xterm.js Terminal - Full PTY integration via node-pty  
✅ **TRACK 4:** Memory System - Obsidian vault with MemoryManager, Flask endpoints  

## Remaining Work

### TRACK 5: OPENCLAW (Partial - Calendar started)

**Still needed:**
1. `workers/openclaw/contacts.py` - Google Contacts API integration
2. `workers/openclaw/reminders.py` - SQLite-backed reminders + plyer notifications
3. `workers/openclaw/web.py` - Brave Search API + Playwright web fetching
4. `workers/openclaw/notes.py` - Notes to memory vault
5. Flask routes in `desktop_app.py`:
   - POST `/openclaw/calendar/create`
   - GET `/openclaw/calendar/upcoming`
   - POST `/openclaw/web/search`
   - POST `/openclaw/notes/create`
   - GET `/openclaw/reminders/due`
6. Register OpenClaw as worker in WorkerManager

**Dependencies to install:**
```bash
cd ~/Desktop/SentinelAI
source venv/bin/activate  # or .\venv\Scripts\activate on Windows
pip install gcsa google-api-python-client google-auth-httplib2 google-auth-oauthlib playwright brave-search-python plyer
playwright install chromium
```

### TRACK 6: SENTINEL EARN EXPANSION + SENTINEL MARKET

**Earn Expansion:**
1. Create `workers/earn/bounty_targets.py` - Fetch HackerOne/Bugcrowd data
2. Create `workers/earn/upwork_scanner.py` - Upwork job scraper with Playwright
3. Create `workers/earn/remoteok_scanner.py` - RemoteOK API integration
4. Create `workers/earn/freelancer_scanner.py` - Freelancer.com RSS parser
5. Add scheduler to Earn worker (runs each scanner on intervals)
6. Add Flask route: GET `/earn/jobs?source=`

**Sentinel Market:**
1. Install Freqtrade in isolated venv:
   ```bash
   python -m venv ~/Desktop/SentinelAI/market/freqtrade_env
   source ~/Desktop/SentinelAI/market/freqtrade_env/bin/activate
   pip install freqtrade
   freqtrade create-userdir --userdir ~/Desktop/SentinelAI/market/freqtrade_data
   ```

2. Create `market/freqtrade_data/config.json`:
   ```json
   {
     "dry_run": true,
     "exchange": {
       "name": "paper_trade"
     },
     "stake_currency": "USDT",
     "max_open_trades": 3,
     "api_server": {
       "enabled": true,
       "listen_ip_address": "127.0.0.1",
       "listen_port": 5003,
       "username": "sentinel",
       "password": "sentinel"
     }
   }
   ```

3. Create `market/freqtrade_manager.py` - Subprocess manager for Freqtrade
4. Create `market/openbb_bridge.py`:
   ```bash
   pip install openbb
   ```
   - `get_stock_data()`, `get_crypto_data()`, `get_news()`, `market_summary()`

5. Add Flask routes:
   - GET `/market/summary`
   - GET `/market/stock/<ticker>`
   - GET `/market/crypto/<symbol>`
   - GET `/market/news/<ticker>`
   - GET `/market/freqtrade/status`
   - POST `/market/freqtrade/backtest` (dry run only)

6. Wire FreqUI iframe in `market_window.html` to localhost:5003

### TRACK 7: HEALTH MONITORING — Grafana + Prometheus

1. Create `monitoring/docker-compose.yml`:
   ```yaml
   version: '3.8'
   services:
     prometheus:
       image: prom/prometheus:latest
       ports:
         - "9090:9090"
       volumes:
         - ./prometheus.yml:/etc/prometheus/prometheus.yml
     grafana:
       image: grafana/grafana:latest
       ports:
         - "3000:3000"
       environment:
         - GF_SECURITY_ADMIN_PASSWORD=sentinel
       volumes:
         - grafana_data:/var/lib/grafana
   volumes:
     grafana_data:
   ```

2. Create `monitoring/prometheus.yml`:
   ```yaml
   global:
     scrape_interval: 15s

   scrape_configs:
     - job_name: 'sentinelai'
       static_configs:
         - targets: ['host.docker.internal:5001']
   ```

3. Add to Flask app (`desktop_app.py`):
   ```bash
   pip install prometheus-client
   ```

   ```python
   from prometheus_client import Counter, Gauge, make_wsgi_app
   from werkzeug.middleware.dispatcher import DispatcherMiddleware

   sentinel_tasks_total = Counter('sentinel_tasks_total', 'Total tasks submitted')
   sentinel_workers_active = Gauge('sentinel_workers_active', 'Active workers')
   sentinel_forge_runs_total = Counter('sentinel_forge_runs_total', 'Total Forge runs')
   sentinel_earn_jobs_found_total = Counter('sentinel_earn_jobs_found_total', 'Total earn jobs found')

   # Wire metrics
   app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {
       '/metrics': make_wsgi_app()
   })
   ```

4. Update appropriate task handlers to increment counters

5. Start monitoring:
   ```bash
   cd ~/Desktop/SentinelAI/monitoring
   docker-compose up -d
   ```

6. Add "Monitoring" link in Orb UI that opens localhost:3000 in worker window

## Environment Variables to Add (.env)

Create `.env.example`:
```bash
# Google Calendar
GOOGLE_CALENDAR_ENABLED=false

# Brave Search (for OpenClaw web search)
BRAVE_API_KEY=your_brave_api_key_here

# Freqtrade (Paper trading only by default)
FREQTRADE_DRY_RUN=true
FREQTRADE_EXCHANGE=paper_trade

# OpenBB
OPENBB_API_KEY=optional_for_premium_data

# Upwork (for scanner)
UPWORK_EMAIL=your_upwork_email
UPWORK_PASSWORD=your_upwork_password

# Sentinel Backend
FLASK_HOST=127.0.0.1
FLASK_PORT=5001
SENTINELAI_AUTH_TOKEN=sentinelai_default_token_change_me
```

## Final Steps After All Tracks Complete

1. **Update README.md** with:
   - New architecture diagram (Orb UI, Worker Windows, Memory Vault, OpenClaw, Market)
   - Setup instructions for each new dependency
   - OpenClaw setup guide (Google Calendar OAuth, Brave API key)
   - Market disclaimer (PAPER TRADING ONLY)
   - Monitoring setup guide

2. **Smoke Test Each Component:**
   ```bash
   cd ~/Desktop/SentinelAI/desktop-shell
   npm start
   ```
   - Verify orb window opens
   - Verify worker window opens (Forge by default)
   - Test IPC routing by typing in orb input
   - Test Monaco editor in Forge window
   - Test terminal output in Forge window
   - Check memory vault is being written to
   - Verify Flask endpoints respond

3. **Final Commit:**
   ```bash
   git add -A
   git commit -m "feat: full SentinelAI overhaul - orb UI, Monaco, xterm, memory vault, OpenClaw, Earn expansion, Sentinel Market, monitoring scaffold"
   git push origin main
   ```

## Critical Safety Rules (DO NOT SKIP)

1. **Forge Approval Gate:** Never add auto-approval to Forge tasks. The human approval flow is sacred.
2. **Market Trading:** NEVER enable live trading. `dry_run: true` is mandatory in Freqtrade config.
3. **API Keys:** All API keys go in `.env`, never hardcoded. `.env.example` has placeholders.
4. **Google OAuth:** Calendar/Contacts require OAuth consent flow on first run. Run in headless-safe environment.

## Known Issues & Workarounds

1. **Monaco Editor peer dependencies:** Use `npm install --legacy-peer-deps`
2. **node-pty on Windows:** May require node-gyp build tools. Install via `npm install --global windows-build-tools` if errors occur.
3. **Playwright Chromium:** First run requires `playwright install chromium` (downloads ~100MB)
4. **Freqtrade in venv:** Use separate venv to avoid dependency conflicts with main SentinelAI venv

## Testing Checklist

- [ ] Orb window launches and displays animated orb
- [ ] Worker window launches alongside orb window
- [ ] Monaco editor loads in Forge window
- [ ] Terminal appears in Forge window and accepts input
- [ ] Memory vault files created in `memory/vault/sessions/`, `forge_logs/`
- [ ] `/api/memory/recent?subdir=sessions` returns JSON
- [ ] `/api/memory/search?q=test` returns JSON
- [ ] OpenClaw calendar connects (if Google credentials configured)
- [ ] Earn jobs populated in `memory/vault/earn_jobs/`
- [ ] Market window shows ticker cards and FreqUI iframe
- [ ] Prometheus `/metrics` endpoint returns data
- [ ] Grafana accessible at localhost:3000

---

**Total Implementation Time Estimate:** 4-6 hours for remaining Tracks 5-7 + final integration testing.

**Next Session Action:** Continue from Track 5 (complete OpenClaw) using this guide as the roadmap.
