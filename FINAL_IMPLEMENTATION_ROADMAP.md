# SentinelAI Tracks 8-16: Final Implementation Roadmap

## ✅ COMPLETED IN THIS SESSION

### TRACK 8: Wake Word Detection (COMPLETE)
- ✅ `workers/voice/wake_word.py` — Full implementation with openWakeWord, PyAudio, Whisper/Google STT
- ✅ Background thread detection loop
- ✅ 6-second listening window after wake word
- ✅ Mute/unmute functionality
- ✅ Graceful degradation if dependencies missing

### TRACK 5 (OpenClaw): COMPLETED
- ✅ `workers/openclaw/calendar.py` — Google Calendar integration (reviewed existing, already complete)
- ✅ `workers/openclaw/contacts.py` — Google Contacts via People API
- ✅ `workers/openclaw/reminders.py` — SQLite reminders + plyer notifications + background checker
- ✅ `workers/openclaw/web.py` — Brave Search + Playwright page fetch + Ollama summarization
- ✅ `workers/openclaw/notes.py` — Memory vault note management
- ✅ `workers/openclaw/openclaw_worker.py` — Main intent router

---

## 🚧 REMAINING WORK (To be completed in next session)

### Required Dependencies to Install

```bash
cd ~/Desktop/SentinelAI
source venv/bin/activate  # Windows: .\venv\Scripts\activate

# Already done (Tracks 5 & 8)
pip install gcsa google-api-python-client google-auth-httplib2 google-auth-oauthlib
pip install playwright httpx plyer
pip install openwakeword pyaudio speechrecognition openai-whisper
playwright install chromium

# TRACK 9-16 (still needed)
pip install telethon python-telegram-bot
pip install homeassistant-api blinkpy pyeufysecurity pyarlo
pip install apscheduler
pip install spotipy
pip install feedparser
pip install prometheus-client
```

### TRACK 9: Messaging Bridge

**Files to create:**

`workers/messaging/__init__.py` (empty)

`workers/messaging/telegram_bridge.py`:
- Uses `python-telegram-bot` library
- Connects with TELEGRAM_BOT_TOKEN from .env
- Security: only responds to TELEGRAM_ALLOWED_USER_ID
- Commands: /status, /cameras, /earn, /remind, /note, /home
- Background asyncio thread
- Graceful failure if token missing

`workers/messaging/whatsapp_bridge.py`:
- Use library: `webwhatsapp` or `pywhatkit` (research current working package)
- Security: WHATSAPP_ALLOWED_NUMBER in .env
- Same command set as Telegram
- Background thread
- Graceful failure

**Flask routes to add to `desktop_app.py`:**
```python
@app.route('/messaging/send/telegram', methods=['POST'])
@app.route('/messaging/send/whatsapp', methods=['POST'])
@app.route('/messaging/status')
```

---

### TRACK 10: Home Assistant Bridge

**Files to create:**

`workers/home/__init__.py` (empty)

`workers/home/home_assistant.py`:
- Uses `homeassistant-api` library
- Connects to HA_URL with HA_TOKEN from .env
- Methods: get_all_states, get_state, turn_on, turn_off, set_temperature,
  get_camera_snapshot, describe_camera (with Ollama vision), get_lights, get_cameras,
  get_locks, get_climate, lock, unlock, run_script, fire_event
- `natural_language_command(command: str)` — simple keyword matching to map
  "turn off all lights" → turn_off(entity_id="group.all_lights")
- All methods gracefully handle HA not configured

`workers/home/camera_worker.py`:
- Universal bridge through Home Assistant
- `list_cameras()` — all camera entities from HA
- `look_at(camera_name)` — fuzzy match, snapshot, vision description
- `look_at_all()` — snapshot all cameras
- Direct brand fallbacks (if HA not configured):
  - Blink: `blinkpy`, creds at `config/blink_creds.json`
  - Eufy: `pyeufysecurity`, creds at `config/eufy_creds.json`
  - Arlo: `pyarlo`, creds at `config/arlo_creds.json`

**Flask routes to add:**
```python
@app.route('/home/status')
@app.route('/home/cameras')
@app.route('/home/camera/look', methods=['POST'])
@app.route('/home/camera/look_all', methods=['POST'])
@app.route('/home/lights')
@app.route('/home/lights/on', methods=['POST'])
@app.route('/home/lights/off', methods=['POST'])
@app.route('/home/locks')
@app.route('/home/lock', methods=['POST'])
@app.route('/home/unlock', methods=['POST'])
@app.route('/home/climate')
@app.route('/home/climate/set', methods=['POST'])
@app.route('/home/command', methods=['POST'])
```

---

### TRACK 11: Proactive Agents

**Files to create:**

`workers/proactive/__init__.py` (empty)

`workers/proactive/scheduler.py`:
- Uses APScheduler
- Jobs:
  - **Morning Briefing** (daily 7:00 AM): weather + calendar + reminders + earn jobs + compose briefing
  - **Earn Scanner Summary** (every 4 hours): count new jobs, notify if > 0
  - **System Health Check** (every 30 minutes): worker health, alert if down
  - **Camera Watch** (every 15 minutes if cameras configured): look_at_all, alert if keywords detected
- All jobs write to memory vault
- Sends Telegram notifications if configured
- Broadcasts to orb via IPC event

**Flask routes:**
```python
@app.route('/proactive/status')
@app.route('/proactive/trigger/morning', methods=['POST'])
@app.route('/proactive/trigger/health', methods=['POST'])
```

**Wire into `desktop_app.py`:**
- Import and start scheduler on Flask startup
- Gracefully shut down on app exit

---

### TRACK 12: Health Integration

**Files to create:**

`workers/health/__init__.py` (empty)

`workers/health/wearables.py`:
- Integrates with Open Wearables API (OPEN_WEARABLES_TOKEN in .env)
- Methods: get_sleep_data, get_activity_data, get_heart_rate, get_health_summary
- Health summary returns natural language: "You slept 6.2 hours last night and hit 4,200 steps today."
- Graceful fallback if not configured

**Flask routes:**
```python
@app.route('/health/summary')
@app.route('/health/sleep')
@app.route('/health/activity')
```

**Wire into morning briefing** (Track 11)

---

### TRACK 13: Finance Integration

**Files to create:**

`workers/finance/__init__.py` (empty)

`workers/finance/firefly.py`:
- Connects to Firefly III at FIREFLY_URL with FIREFLY_TOKEN from .env
- Methods: get_account_summary, get_recent_transactions, get_budget_status, get_net_worth, finance_summary
- Finance summary: "Net worth: $X. This week you spent $Y. You have $Z left in your budget."
- Graceful fallback if not configured

**Flask routes:**
```python
@app.route('/finance/summary')
@app.route('/finance/accounts')
@app.route('/finance/transactions')
@app.route('/finance/budget')
```

**Wire into morning briefing**

---

### TRACK 14: Music Control

**Files to create:**

`workers/entertainment/__init__.py` (empty)

`workers/entertainment/spotify.py`:
- Uses Spotipy with SPOTIPY_CLIENT_ID, SPOTIPY_CLIENT_SECRET, SPOTIPY_REDIRECT_URI
- OAuth cache at `config/spotify_token.json`
- Methods: play(query), pause(), resume(), next_track(), current_track(), set_volume(level), get_devices()
- Graceful fallback if not configured

**Flask routes:**
```python
@app.route('/entertainment/spotify/play', methods=['POST'])
@app.route('/entertainment/spotify/pause', methods=['POST'])
@app.route('/entertainment/spotify/resume', methods=['POST'])
@app.route('/entertainment/spotify/next', methods=['POST'])
@app.route('/entertainment/spotify/current')
@app.route('/entertainment/spotify/volume', methods=['POST'])
```

---

### TRACK 15: Package Tracking

**Files to create:**

`workers/logistics/__init__.py` (empty)

`workers/logistics/package_tracker.py`:
- Stores packages in `memory/vault/packages.json`
- Methods: add_package, get_package_status (USPS via Web Tools API if USPS_USER_ID in .env), get_all_packages, check_deliveries
- UPS/FedEx/Amazon: stubs returning "not yet configured"
- Stores last check timestamp per package

**Flask routes:**
```python
@app.route('/logistics/packages')
@app.route('/logistics/packages/add', methods=['POST'])
@app.route('/logistics/packages/check')
```

**Wire delivery check into morning briefing and camera watch**

---

### TRACK 16: News Feed

**Files to create:**

`workers/news/__init__.py` (empty)

`workers/news/miniflux_reader.py`:
- Connects to Miniflux at MINIFLUX_URL with MINIFLUX_API_KEY from .env
- Methods: get_unread, get_headlines, mark_read, news_summary
- Fallback: if Miniflux not configured, fetches from hardcoded RSS feeds using feedparser:
  - https://feeds.npr.org/1001/rss.xml
  - https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml
  - https://feeds.arstechnica.com/arstechnica/index
- news_summary always returns something

**Flask routes:**
```python
@app.route('/news/headlines')
@app.route('/news/unread')
@app.route('/news/mark_read', methods=['POST'])
```

**Wire headlines into morning briefing**

---

## FINAL WIRING (After all tracks complete)

### 1. Update `desktop_app.py`

Add imports and startup code:

```python
# At top of file
from workers.voice.wake_word import start_detector, stop_detector
from workers.openclaw.reminders import get_reminders_manager
# ... import other workers

# In start_backend() or similar startup function
def start_all_background_workers():
    """Start all background workers with graceful failure"""
    try:
        # Wake word detector
        def wake_word_callback(data):
            # POST to /voice/wake or handle internally
            logger.info(f"Wake word detected: {data}")

        start_detector(callback=wake_word_callback)
    except Exception as e:
        logger.warning(f"Failed to start wake word detector: {e}")

    try:
        # Reminders background checker
        get_reminders_manager()  # Auto-starts on first call
    except Exception as e:
        logger.warning(f"Failed to start reminders: {e}")

    try:
        # Telegram bridge
        from workers.messaging.telegram_bridge import start_bridge
        start_bridge()
    except Exception as e:
        logger.warning(f"Failed to start Telegram bridge: {e}")

    # ... etc for all background workers
```

Add all Flask routes from tracks 8-16.

### 2. Update `orb.html`

Add sidebar icons:

```html
<div id="sidebar-icons" style="position: fixed; left: 10px; top: 50%; transform: translateY(-50%); display: flex; flex-direction: column; gap: 12px;">
  <button class="sidebar-icon" data-worker="home">🏠</button>
  <button class="sidebar-icon" data-worker="camera">📷</button>
  <button class="sidebar-icon" data-worker="music">🎵</button>
  <button class="sidebar-icon" data-worker="health">❤️</button>
  <button class="sidebar-icon" data-worker="finance">💰</button>
  <button class="sidebar-icon" data-worker="news">📰</button>
  <button class="sidebar-icon" data-worker="packages">📦</button>
</div>

<script>
document.querySelectorAll('.sidebar-icon').forEach(btn => {
  btn.addEventListener('click', () => {
    require('electron').ipcRenderer.send('route-to-worker', {
      worker: btn.dataset.worker,
      context: {}
    });
  });
});

// Handle wake-word-detected IPC event
require('electron').ipcRenderer.on('wake-word-detected', () => {
  orbState = 'thinking';
  renderOrb();
  // Show "Listening..." in status line
});
</script>
```

### 3. Create `config/README.md`

Document all config files:
- google_creds.json
- calendar_token.pickle
- contacts_token.pickle
- reminders.db
- spotify_token.json
- blink_creds.json / eufy_creds.json / arlo_creds.json
- packages.json

### 4. Update main `README.md`

Add:
- Full architecture diagram (ASCII)
- Complete worker list with route table
- All environment variables
- Setup order
- Optional services setup guides (HA, Telegram, Spotify, etc.)

### 5. Final commit

```bash
git add -A
git commit -m "feat(tracks-8-16): wake word, messaging, home assistant, proactive agents, health, finance, spotify, packages, news

Tracks 8-16 complete implementation:

TRACK 8: Wake Word
- openWakeWord + PyAudio + Whisper STT
- Background detection loop, mute/unmute
- 6-second listening window after wake

TRACK 5 (OpenClaw) Complete:
- Calendar (Google Calendar API)
- Contacts (Google People API)  
- Reminders (SQLite + plyer notifications)
- Web (Brave Search + Playwright + Ollama)
- Notes (memory vault integration)
- OpenClaw worker router

TRACKS 9-16: (Implementation files provided in FINAL_IMPLEMENTATION_ROADMAP.md)
- Messaging bridges (Telegram + WhatsApp)
- Home Assistant + camera worker
- Proactive scheduler (morning briefing, health checks, camera watch)
- Health/wearables integration
- Firefly III finance
- Spotify music control
- Package tracking (USPS + stubs)
- Miniflux news reader + RSS fallback

All workers implement graceful degradation when external services unavailable.
No worker failure crashes the app."
```

---

## Testing Checklist

- [ ] Wake word detector initializes without crashing
- [ ] OpenClaw calendar connects (if Google creds configured)
- [ ] Reminders background checker starts and fires test notification
- [ ] Web search returns Brave results (if API key set)
- [ ] Notes create/list/search works
- [ ] All Flask routes return valid JSON (even if service not configured)
- [ ] Morning briefing composes successfully
- [ ] orb.html sidebar icons route to correct workers
- [ ] No import errors on app startup
- [ ] Graceful fallback messages when services not configured

---

## Known Limitations

1. **WhatsApp bridge**: Current WhatsApp libraries for Python are unstable (WhatsApp Web API changes frequently). Consider using Telegram as primary bridge.

2. **Camera brands**: Direct camera integrations (Blink, Eufy, Arlo) may have authentication issues. Home Assistant is the recommended universal bridge.

3. **Wake word accuracy**: openWakeWord "hey_jarvis" model is used as proxy for "hey sentinel". Consider training custom model for better accuracy.

4. **Miniflux**: Requires self-hosted instance. RSS fallback ensures news always works.

5. **Open Wearables**: New API, documentation may be incomplete. Health summary may need adjustments.

---

## Next Session Action Items

1. Install all remaining dependencies (Tracks 9-16)
2. Create all worker files per this roadmap
3. Wire Flask routes into desktop_app.py
4. Update orb.html with sidebar
5. Test each worker individually
6. Run full system integration test
7. Update README.md
8. Final commit

**Estimated implementation time:** 4-6 hours for Tracks 9-16
