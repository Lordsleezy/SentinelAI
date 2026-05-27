# SentinelAI - Backend Integration Plan

**Version:** 1.0.0  
**Date:** May 26, 2026  
**Status:** Official Electron Integration Blueprint  
**Purpose:** Definitive architecture for future Electron desktop shell integration

---

## 📋 DOCUMENT PURPOSE

This document defines the **OFFICIAL future desktop architecture** for SentinelAI.

This is the **blueprint** for:
- Electron desktop shell integration
- Unified command center vision
- Runtime lifecycle management
- Process supervision strategy
- Future UI module architecture

**CRITICAL:** This document becomes the authoritative reference for all future Electron implementation work.

---

## 🎯 INTEGRATION PHILOSOPHY

### Backend Ownership Model

**Principle:** Python backend owns all business logic, data, and operations.

**Ownership Boundaries:**

**Python Backend Owns:**
- All business logic (scanning, execution, learning)
- All data persistence (database, queue, state)
- All worker orchestration
- All health monitoring
- All crash recovery
- All safety constraints
- All API endpoints
- All external integrations (GitHub, Ollama, platforms)

**Electron Shell Owns:**
- User interface rendering
- System tray integration
- Window management
- Backend process supervision
- IPC communication
- Frontend routing
- UI state management
- Desktop notifications

**Shared Responsibility:**
- Authentication (backend validates, frontend stores token)
- Configuration (backend reads .env, frontend provides UI)
- Logging (backend generates, frontend displays)

---

### Frontend/Backend Separation

**Architecture Pattern:** Thin client, thick server

**Separation Strategy:**

```
┌─────────────────────────────────────────────────────────────┐
│                    ELECTRON SHELL                           │
│                   (Presentation Layer)                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  - UI Rendering (React/Vue/Vanilla JS)                     │
│  - User Input Handling                                     │
│  - Frontend Routing                                        │
│  - State Management (UI state only)                        │
│  - Desktop Integration (tray, notifications)               │
│                                                             │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      │ HTTP/REST API
                      │ (localhost:5001)
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                  PYTHON BACKEND                             │
│                 (Business Logic Layer)                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  - All Business Logic                                      │
│  - Data Persistence                                        │
│  - Worker Orchestration                                    │
│  - External Integrations                                   │
│  - Safety Constraints                                      │
│  - Health Monitoring                                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Communication Protocol:**
- Primary: HTTP REST API (existing Flask endpoints)
- Future: WebSocket for real-time updates (optional enhancement)
- IPC: Electron IPC for process management only

**Data Flow:**
- Frontend → Backend: HTTP requests (GET/POST)
- Backend → Frontend: HTTP responses (JSON)
- Backend → Frontend: WebSocket events (future)
- Electron Main → Renderer: IPC messages (process status)

---

### Modular Runtime Architecture

**Module Isolation:**

Each module is independently:
- Loadable (can be enabled/disabled)
- Testable (can be tested in isolation)
- Deployable (can be updated independently)
- Observable (has its own metrics)

**Module Structure:**
```
Module
├── Frontend Component (Electron renderer)
├── Backend API Endpoints (Flask routes)
├── Business Logic (Python modules)
├── Data Models (Database tables)
└── Tests (Integration tests)
```

**Module Communication:**
- Modules communicate via backend API
- No direct frontend-to-frontend communication
- Backend coordinates all module interactions

---

### Process Boundaries

**Process Model:**

```
┌─────────────────────────────────────────────────────────────┐
│                  ELECTRON MAIN PROCESS                      │
│                                                             │
│  - Window Management                                       │
│  - System Tray                                             │
│  - Backend Process Supervision                             │
│  - IPC Coordination                                        │
│  - Auto-Update (future)                                    │
│                                                             │
└─────────────────────┬───────────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        │             │             │
        ▼             ▼             ▼
┌───────────┐  ┌───────────┐  ┌───────────┐
│ Renderer  │  │ Renderer  │  │  Python   │
│ Process 1 │  │ Process 2 │  │  Backend  │
│ (Main UI) │  │ (Settings)│  │  Process  │
└───────────┘  └───────────┘  └───────────┘
```

**Process Isolation:**
- Electron main process: Supervisor
- Electron renderer processes: UI windows
- Python backend process: Child process of main
- Each process has independent crash domain

**Process Communication:**
- Main ↔ Renderer: Electron IPC
- Main ↔ Backend: Child process management
- Renderer ↔ Backend: HTTP REST API
- Renderer ↔ Renderer: Via main process IPC

---

### Observability Goals

**Monitoring Layers:**

1. **Backend Observability** (existing)
   - Health metrics (CPU, RAM, queue)
   - Worker status
   - Task execution logs
   - Learning analytics

2. **Frontend Observability** (new)
   - UI performance metrics
   - User interaction tracking
   - Error boundary logging
   - Network request timing

3. **Process Observability** (new)
   - Backend process health
   - Process restart count
   - IPC message latency
   - Window lifecycle events

**Logging Strategy:**
- Backend: Python logging (existing)
- Frontend: Console logging + error tracking
- Process: Electron main process logging
- Unified: All logs aggregated in backend database (future)

---

## 🐍 PYTHON BACKEND LIFECYCLE

### Startup Sequence

**Detailed Startup Flow:**

```
1. Electron Main Process Starts
   ├─ Load configuration
   ├─ Initialize logging
   └─ Create splash screen

2. Python Backend Launch
   ├─ Validate Python installation
   ├─ Check Python version (>=3.8)
   ├─ Validate virtual environment (optional)
   └─ Spawn Python process: python desktop_app.py

3. Backend Initialization (desktop_app.py)
   ├─ Load environment variables (.env)
   ├─ Configure logging
   ├─ Initialize database (db.init_db())
   ├─ Initialize learning memory (lm.initialize_learning_system())
   ├─ Initialize task queue (qm.initialize_queue())
   ├─ Perform crash recovery (wd.recover_from_crash())
   ├─ Initialize worker manager (wm.initialize_workers())
   ├─ Start watchdog (wd.get_watchdog().start())
   ├─ Start health monitor (hm.get_monitor().start())
   └─ Start Flask server (app.run())

4. Readiness Polling (Electron Main)
   ├─ Poll health endpoint: GET /api/status
   ├─ Retry every 500ms
   ├─ Timeout after 30 seconds
   └─ On success: Backend ready

5. Dashboard Initialization (Electron Renderer)
   ├─ Close splash screen
   ├─ Open main window
   ├─ Load dashboard UI
   ├─ Fetch initial data
   └─ Start periodic refresh

6. Runtime Monitoring Begins
   ├─ Electron monitors backend process
   ├─ Backend monitors workers
   ├─ Watchdog monitors system health
   └─ Health monitor tracks metrics
```

**Startup Timing:**
- Electron launch: <1 second
- Python backend spawn: 1-2 seconds
- Backend initialization: 2-5 seconds
- Total startup time: 3-8 seconds

---

### Dependency Validation

**Pre-Launch Checks:**

```javascript
// Electron main process
async function validateDependencies() {
  const checks = {
    python: await checkPythonInstalled(),
    pythonVersion: await checkPythonVersion(),
    ollama: await checkOllamaRunning(),
    database: await checkDatabaseExists(),
    env: await checkEnvFileExists()
  };
  
  if (!checks.python) {
    showError("Python not found. Please install Python 3.8+");
    return false;
  }
  
  if (!checks.pythonVersion) {
    showError("Python version must be 3.8 or higher");
    return false;
  }
  
  if (!checks.ollama) {
    showWarning("Ollama not running. Some features will be unavailable.");
    // Continue anyway - not critical for startup
  }
  
  if (!checks.env) {
    showWarning(".env file not found. Using defaults.");
    // Continue anyway - will use defaults
  }
  
  return true;
}
```

**Dependency Checks:**
1. **Python Installation** - Check `python --version`
2. **Python Version** - Verify >=3.8
3. **Python Packages** - Check requirements.txt installed (optional)
4. **Ollama** - Check http://localhost:11434/api/tags (warning only)
5. **Database** - Check data/sentinelai.db exists (create if missing)
6. **.env File** - Check .env exists (warning only)

**Failure Handling:**
- Critical failures (Python missing): Show error, exit
- Non-critical failures (Ollama offline): Show warning, continue
- Missing files (.env): Show warning, use defaults

---

### Database Initialization

**Database Startup Flow:**

```python
# In desktop_app.py start_backend()
def start_backend():
    logger.info("Starting SentinelAI backend...")
    
    # Initialize database
    try:
        db.init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.critical(f"Database initialization failed: {e}")
        raise  # Critical failure - cannot continue
```

**Database Checks:**
1. Create data directory if missing
2. Create database file if missing
3. Create all tables if missing
4. Verify table schemas
5. Run migrations if needed (future)

**Migration Strategy (Future):**
```python
def run_migrations():
    current_version = get_db_version()
    target_version = LATEST_VERSION
    
    if current_version < target_version:
        for version in range(current_version + 1, target_version + 1):
            apply_migration(version)
            set_db_version(version)
```

---

### Service Initialization

**Service Startup Order:**

```python
# Ordered initialization (dependencies matter)
def start_backend():
    # 1. Database (required by all)
    db.init_db()
    
    # 2. Learning memory (required by scanner)
    lm.initialize_learning_system()
    
    # 3. Task queue (required by workers)
    qm.initialize_queue()
    
    # 4. Crash recovery (resets stale tasks)
    wd.recover_from_crash()
    
    # 5. Worker manager (requires queue)
    wm.initialize_workers(max_workers=3)
    
    # 6. Watchdog (monitors workers)
    watchdog = wd.initialize_watchdog(check_interval=30)
    watchdog.start()
    
    # 7. Health monitor (monitors system)
    monitor = hm.initialize_health_monitor(sample_interval=60)
    monitor.start()
    
    # 8. Flask server (last - provides API)
    flask_thread = threading.Thread(target=run_flask_app, daemon=True)
    flask_thread.start()
```

**Service Dependencies:**
```
Flask Server
    ↓
Health Monitor, Watchdog
    ↓
Worker Manager
    ↓
Task Queue
    ↓
Learning Memory
    ↓
Database
```

**Initialization Timing:**
- Database: <100ms
- Learning memory: <100ms
- Task queue: <100ms
- Crash recovery: <500ms
- Worker manager: <100ms
- Watchdog: <50ms
- Health monitor: <50ms
- Flask server: <500ms
- **Total: ~1.5 seconds**

---

### Health Readiness

**Readiness Endpoint:**

```python
@app.route('/api/health/ready')
def health_ready():
    """
    Readiness check for Electron.
    Returns 200 when backend is fully initialized and ready.
    """
    checks = {
        'database': check_database_ready(),
        'queue': check_queue_ready(),
        'workers': check_workers_ready(),
        'watchdog': check_watchdog_ready(),
        'health_monitor': check_health_monitor_ready()
    }
    
    all_ready = all(checks.values())
    
    return jsonify({
        'ready': all_ready,
        'checks': checks,
        'timestamp': datetime.now().isoformat()
    }), 200 if all_ready else 503
```

**Readiness Criteria:**
- Database initialized ✓
- Queue initialized ✓
- Workers created (not necessarily started) ✓
- Watchdog running ✓
- Health monitor running ✓
- Flask server responding ✓

**Electron Polling:**
```javascript
async function waitForBackendReady() {
  const maxAttempts = 60;  // 30 seconds
  const interval = 500;     // 500ms
  
  for (let i = 0; i < maxAttempts; i++) {
    try {
      const response = await fetch('http://localhost:5001/api/health/ready');
      const data = await response.json();
      
      if (data.ready) {
        return true;
      }
    } catch (error) {
      // Backend not responding yet
    }
    
    await sleep(interval);
  }
  
  throw new Error('Backend failed to become ready within 30 seconds');
}
```

---

### Runtime Stabilization

**Stabilization Period:**

After backend reports ready, wait for stabilization:

```javascript
async function waitForStabilization() {
  // Backend is ready, but give it time to stabilize
  await sleep(1000);  // 1 second stabilization period
  
  // Verify stability
  const health = await fetch('http://localhost:5001/api/system/health');
  const data = await health.json();
  
  if (data.cpu_percent > 90 || data.ram_percent > 90) {
    showWarning('System under high load. Performance may be degraded.');
  }
}
```

**Stabilization Checks:**
- CPU usage <90%
- RAM usage <90%
- No errors in recent logs
- All workers idle or executing

---

### Shutdown Sequence

**Graceful Shutdown Flow:**

```python
def shutdown_backend():
    logger.info("Shutting down SentinelAI backend...")
    
    # 1. Stop accepting new tasks
    backend_state["running"] = False
    
    # 2. Pause all workers
    manager = wm.get_manager()
    manager.pause_all()
    
    # 3. Wait for current tasks to complete (max 30s)
    wait_for_workers_idle(timeout=30)
    
    # 4. Stop workers
    manager.stop_all()
    
    # 5. Stop watchdog
    watchdog = wd.get_watchdog()
    watchdog.stop()
    
    # 6. Stop health monitor
    monitor = hm.get_monitor()
    monitor.stop()
    
    # 7. Flush database
    db.get_conn().close()
    
    # 8. Stop Flask server
    # (Flask will stop when main thread exits)
    
    logger.info("Backend shutdown complete")
```

**Shutdown Timing:**
- Pause workers: <100ms
- Wait for idle: 0-30 seconds
- Stop workers: <500ms
- Stop monitors: <100ms
- Database flush: <100ms
- **Total: 1-31 seconds**

**Force Shutdown:**
If graceful shutdown times out:
```javascript
// Electron main process
function forceShutdown() {
  if (backendProcess) {
    backendProcess.kill('SIGTERM');
    
    setTimeout(() => {
      if (backendProcess && !backendProcess.killed) {
        backendProcess.kill('SIGKILL');
      }
    }, 5000);  // Force kill after 5s
  }
}
```

---

## ⚡ ELECTRON LAUNCH FLOW

### Detailed Launch Sequence

**Step-by-Step Flow:**

```
1. Electron App Starts
   ├─ app.on('ready')
   ├─ Load configuration from config.json
   ├─ Initialize logging
   └─ Create splash screen window

2. Splash Screen Displayed
   ├─ Show "SentinelAI" logo
   ├─ Show "Initializing..." message
   └─ Show progress bar (0%)

3. Python Backend Launched
   ├─ Update splash: "Starting backend..." (20%)
   ├─ Validate dependencies
   ├─ Spawn Python process
   └─ Capture stdout/stderr

4. Dependency Validation
   ├─ Update splash: "Checking dependencies..." (40%)
   ├─ Check Python installation
   ├─ Check Ollama status
   └─ Check database

5. Readiness Polling Begins
   ├─ Update splash: "Waiting for backend..." (60%)
   ├─ Poll /api/health/ready every 500ms
   ├─ Update progress based on checks
   └─ Timeout after 30 seconds

6. Health Endpoint Validation
   ├─ Update splash: "Validating health..." (80%)
   ├─ GET /api/system/health
   ├─ Verify all systems operational
   └─ Check for warnings

7. Dashboard Opened
   ├─ Update splash: "Opening dashboard..." (90%)
   ├─ Close splash screen
   ├─ Create main window
   ├─ Load dashboard URL (http://localhost:5001)
   └─ Show main window

8. Runtime Monitoring Begins
   ├─ Update splash: "Ready!" (100%)
   ├─ Start backend process monitor
   ├─ Start periodic health checks
   ├─ Create system tray icon
   └─ Hide splash screen
```

**Total Launch Time:** 3-10 seconds (typical: 5 seconds)

---

### Splash Screen Implementation

**Splash Window:**

```javascript
function createSplashScreen() {
  splashWindow = new BrowserWindow({
    width: 400,
    height: 300,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  });
  
  splashWindow.loadFile('splash.html');
  splashWindow.center();
}
```

**Splash HTML:**

```html
<!DOCTYPE html>
<html>
<head>
  <style>
    body {
      background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
      color: #00d4ff;
      font-family: 'Segoe UI', sans-serif;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      height: 100vh;
      margin: 0;
    }
    .logo { font-size: 48px; font-weight: bold; margin-bottom: 20px; }
    .message { font-size: 18px; margin-bottom: 20px; }
    .progress-bar {
      width: 300px;
      height: 4px;
      background: #0f3460;
      border-radius: 2px;
      overflow: hidden;
    }
    .progress-fill {
      height: 100%;
      background: #00d4ff;
      width: 0%;
      transition: width 0.3s ease;
    }
  </style>
</head>
<body>
  <div class="logo">SentinelAI</div>
  <div class="message" id="message">Initializing...</div>
  <div class="progress-bar">
    <div class="progress-fill" id="progress"></div>
  </div>
  
  <script>
    const { ipcRenderer } = require('electron');
    
    ipcRenderer.on('splash-message', (event, message) => {
      document.getElementById('message').textContent = message;
    });
    
    ipcRenderer.on('splash-progress', (event, percent) => {
      document.getElementById('progress').style.width = percent + '%';
    });
  </script>
</body>
</html>
```

**Progress Updates:**

```javascript
function updateSplash(message, progress) {
  if (splashWindow) {
    splashWindow.webContents.send('splash-message', message);
    splashWindow.webContents.send('splash-progress', progress);
  }
}
```

---

### Backend Launch Implementation

**Process Spawning:**

```javascript
const { spawn } = require('child_process');
const path = require('path');

function launchBackend() {
  const pythonPath = findPython();  // Find python executable
  const scriptPath = path.join(__dirname, '..', 'backend', 'desktop_app.py');
  
  backendProcess = spawn(pythonPath, [scriptPath], {
    cwd: path.join(__dirname, '..', 'backend'),
    env: { ...process.env },
    stdio: ['ignore', 'pipe', 'pipe']
  });
  
  // Capture stdout
  backendProcess.stdout.on('data', (data) => {
    console.log(`[Backend] ${data.toString()}`);
    logToFile('backend.log', data.toString());
  });
  
  // Capture stderr
  backendProcess.stderr.on('data', (data) => {
    console.error(`[Backend Error] ${data.toString()}`);
    logToFile('backend-error.log', data.toString());
  });
  
  // Handle exit
  backendProcess.on('exit', (code, signal) => {
    console.log(`Backend exited with code ${code}, signal ${signal}`);
    handleBackendExit(code, signal);
  });
  
  // Handle errors
  backendProcess.on('error', (error) => {
    console.error(`Backend spawn error: ${error}`);
    showError(`Failed to start backend: ${error.message}`);
  });
  
  return backendProcess;
}
```

**Python Detection:**

```javascript
function findPython() {
  const candidates = [
    'python',
    'python3',
    'python3.8',
    'python3.9',
    'python3.10',
    'python3.11',
    'C:\\Python39\\python.exe',
    'C:\\Python310\\python.exe',
    'C:\\Python311\\python.exe'
  ];
  
  for (const candidate of candidates) {
    try {
      const result = execSync(`${candidate} --version`, { encoding: 'utf8' });
      if (result.includes('Python 3.')) {
        return candidate;
      }
    } catch (error) {
      // Try next candidate
    }
  }
  
  throw new Error('Python 3.8+ not found');
}
```

---

### Readiness Polling Strategy

**Polling Implementation:**

```javascript
async function pollBackendReady() {
  const maxAttempts = 60;
  const interval = 500;
  let attempt = 0;
  
  while (attempt < maxAttempts) {
    try {
      const response = await fetch('http://localhost:5001/api/health/ready', {
        method: 'GET',
        timeout: 2000
      });
      
      if (response.ok) {
        const data = await response.json();
        
        if (data.ready) {
          updateSplash('Backend ready!', 80);
          return true;
        } else {
          // Partially ready - update progress
          const readyCount = Object.values(data.checks).filter(v => v).length;
          const totalChecks = Object.keys(data.checks).length;
          const progress = 60 + (readyCount / totalChecks) * 20;
          updateSplash(`Initializing (${readyCount}/${totalChecks})...`, progress);
        }
      }
    } catch (error) {
      // Backend not responding yet
      updateSplash(`Waiting for backend (${attempt + 1}/${maxAttempts})...`, 60);
    }
    
    await sleep(interval);
    attempt++;
  }
  
  throw new Error('Backend failed to become ready');
}
```

**Exponential Backoff (Alternative):**

```javascript
async function pollBackendReadyWithBackoff() {
  let interval = 100;  // Start with 100ms
  const maxInterval = 2000;  // Max 2 seconds
  const timeout = 30000;  // 30 second total timeout
  const startTime = Date.now();
  
  while (Date.now() - startTime < timeout) {
    try {
      const response = await fetch('http://localhost:5001/api/health/ready');
      if (response.ok) {
        const data = await response.json();
        if (data.ready) return true;
      }
    } catch (error) {
      // Not ready yet
    }
    
    await sleep(interval);
    interval = Math.min(interval * 1.5, maxInterval);  // Exponential backoff
  }
  
  throw new Error('Backend readiness timeout');
}
```

---

### Health Validation

**Health Check:**

```javascript
async function validateBackendHealth() {
  try {
    const response = await fetch('http://localhost:5001/api/system/health');
    const health = await response.json();
    
    // Check for critical issues
    if (health.cpu_percent > 95) {
      showWarning('CPU usage critical. System may be slow.');
    }
    
    if (health.ram_percent > 95) {
      showWarning('Memory usage critical. System may be unstable.');
    }
    
    if (health.queue_depth > 400) {
      showWarning('Task queue critical. System may be overloaded.');
    }
    
    // Check Ollama
    if (health.ollama_status !== 'running') {
      showWarning('Ollama not running. AI features unavailable.');
    }
    
    return true;
  } catch (error) {
    showError(`Health check failed: ${error.message}`);
    return false;
  }
}
```

---

### Dashboard Initialization

**Main Window Creation:**

```javascript
function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 800,
    minHeight: 600,
    show: false,  // Don't show until ready
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    }
  });
  
  // Load dashboard
  mainWindow.loadURL('http://localhost:5001');
  
  // Show when ready
  mainWindow.once('ready-to-show', () => {
    if (splashWindow) {
      splashWindow.close();
      splashWindow = null;
    }
    mainWindow.show();
    mainWindow.focus();
  });
  
  // Handle close
  mainWindow.on('close', (event) => {
    if (!app.isQuitting) {
      event.preventDefault();
      mainWindow.hide();
    }
  });
}
```

**Preload Script:**

```javascript
// preload.js
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electron', {
  // System tray controls
  minimize: () => ipcRenderer.send('minimize-to-tray'),
  quit: () => ipcRenderer.send('quit-app'),
  
  // Backend controls
  restartBackend: () => ipcRenderer.send('restart-backend'),
  
  // Notifications
  notify: (title, body) => ipcRenderer.send('show-notification', { title, body }),
  
  // Events
  onBackendStatus: (callback) => ipcRenderer.on('backend-status', callback)
});
```

---

### Runtime Monitoring

**Backend Process Monitor:**

```javascript
function startBackendMonitor() {
  // Check backend health every 10 seconds
  setInterval(async () => {
    try {
      const response = await fetch('http://localhost:5001/api/status', {
        timeout: 5000
      });
      
      if (!response.ok) {
        handleBackendUnhealthy();
      }
    } catch (error) {
      handleBackendUnhealthy();
    }
  }, 10000);
  
  // Monitor process exit
  if (backendProcess) {
    backendProcess.on('exit', (code, signal) => {
      handleBackendExit(code, signal);
    });
  }
}

function handleBackendUnhealthy() {
  console.warn('Backend unhealthy, attempting restart...');
  
  // Show notification
  new Notification('SentinelAI', {
    body: 'Backend unhealthy. Restarting...'
  });
  
  // Restart backend
  restartBackend();
}

function handleBackendExit(code, signal) {
  console.error(`Backend exited: code=${code}, signal=${signal}`);
  
  if (code !== 0 && !app.isQuitting) {
    // Unexpected exit - restart
    new Notification('SentinelAI', {
      body: 'Backend crashed. Restarting...'
    });
    
    setTimeout(() => {
      restartBackend();
    }, 2000);
  }
}
```

---

## 🔧 PROCESS MANAGEMENT

### Child Process Handling

**Process Lifecycle:**

```javascript
class BackendProcess {
  constructor() {
    this.process = null;
    this.pid = null;
    this.restartCount = 0;
    this.maxRestarts = 5;
    this.restartWindow = 60000;  // 1 minute
    this.restartTimes = [];
  }
  
  async start() {
    if (this.process) {
      throw new Error('Backend already running');
    }
    
    this.process = launchBackend();
    this.pid = this.process.pid;
    
    console.log(`Backend started with PID ${this.pid}`);
    
    // Setup monitoring
    this.setupMonitoring();
  }
  
  async stop() {
    if (!this.process) return;
    
    console.log('Stopping backend...');
    
    // Try graceful shutdown first
    try {
      await fetch('http://localhost:5001/api/shutdown', {
        method: 'POST',
        timeout: 5000
      });
      
      // Wait for process to exit
      await this.waitForExit(5000);
    } catch (error) {
      // Graceful shutdown failed, force kill
      this.forceKill();
    }
    
    this.process = null;
    this.pid = null;
  }
  
  async restart() {
    console.log('Restarting backend...');
    
    // Check restart rate
    if (!this.canRestart()) {
      throw new Error('Too many restarts. Manual intervention required.');
    }
    
    await this.stop();
    await sleep(1000);
    await this.start();
    
    this.recordRestart();
  }
  
  canRestart() {
    const now = Date.now();
    this.restartTimes = this.restartTimes.filter(t => now - t < this.restartWindow);
    return this.restartTimes.length < this.maxRestarts;
  }
  
  recordRestart() {
    this.restartTimes.push(Date.now());
    this.restartCount++;
  }
  
  forceKill() {
    if (this.process) {
      this.process.kill('SIGTERM');
      
      setTimeout(() => {
        if (this.process && !this.process.killed) {
          this.process.kill('SIGKILL');
        }
      }, 5000);
    }
  }
  
  async waitForExit(timeout) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new Error('Process exit timeout'));
      }, timeout);
      
      this.process.once('exit', () => {
        clearTimeout(timer);
        resolve();
      });
    });
  }
  
  setupMonitoring() {
    this.process.on('exit', (code, signal) => {
      this.handleExit(code, signal);
    });
    
    this.process.on('error', (error) => {
      this.handleError(error);
    });
  }
  
  handleExit(code, signal) {
    console.log(`Backend exited: code=${code}, signal=${signal}`);
    
    if (code !== 0 && !app.isQuitting) {
      // Unexpected exit
      this.restart().catch(error => {
        console.error(`Restart failed: ${error.message}`);
        showError('Backend failed to restart. Please restart the application.');
      });
    }
  }
  
  handleError(error) {
    console.error(`Backend error: ${error.message}`);
  }
}

// Global instance
const backend = new BackendProcess();
```

---

### PID Tracking

**PID Management:**

```javascript
class PIDManager {
  constructor() {
    this.pidFile = path.join(app.getPath('userData'), 'backend.pid');
  }
  
  write(pid) {
    fs.writeFileSync(this.pidFile, pid.toString());
  }
  
  read() {
    try {
      return parseInt(fs.readFileSync(this.pidFile, 'utf8'));
    } catch (error) {
      return null;
    }
  }
  
  clear() {
    try {
      fs.unlinkSync(this.pidFile);
    } catch (error) {
      // Ignore
    }
  }
  
  isRunning(pid) {
    try {
      process.kill(pid, 0);  // Signal 0 checks if process exists
      return true;
    } catch (error) {
      return false;
    }
  }
  
  cleanup() {
    const pid = this.read();
    if (pid && this.isRunning(pid)) {
      try {
        process.kill(pid, 'SIGTERM');
      } catch (error) {
        console.error(`Failed to kill process ${pid}: ${error.message}`);
      }
    }
    this.clear();
  }
}

const pidManager = new PIDManager();
```

---

### Crash Detection

**Crash Detection Strategy:**

```javascript
class CrashDetector {
  constructor(backend) {
    this.backend = backend;
    this.healthCheckInterval = 10000;  // 10 seconds
    this.healthCheckTimeout = 5000;    // 5 seconds
    this.consecutiveFailures = 0;
    this.maxConsecutiveFailures = 3;
    this.timer = null;
  }
  
  start() {
    this.timer = setInterval(() => {
      this.checkHealth();
    }, this.healthCheckInterval);
  }
  
  stop() {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }
  
  async checkHealth() {
    try {
      const response = await fetch('http://localhost:5001/api/health/ready', {
        timeout: this.healthCheckTimeout
      });
      
      if (response.ok) {
        const data = await response.json();
        if (data.ready) {
          this.consecutiveFailures = 0;
          return;
        }
      }
      
      this.handleFailure();
    } catch (error) {
      this.handleFailure();
    }
  }
  
  handleFailure() {
    this.consecutiveFailures++;
    
    console.warn(`Health check failed (${this.consecutiveFailures}/${this.maxConsecutiveFailures})`);
    
    if (this.consecutiveFailures >= this.maxConsecutiveFailures) {
      console.error('Backend crashed or unresponsive');
      this.handleCrash();
    }
  }
  
  handleCrash() {
    new Notification('SentinelAI', {
      body: 'Backend crashed. Restarting...'
    });
    
    this.backend.restart().catch(error => {
      console.error(`Restart failed: ${error.message}`);
      showError('Failed to restart backend. Please restart the application.');
    });
    
    this.consecutiveFailures = 0;
  }
}

const crashDetector = new CrashDetector(backend);
```

---

### Restart Strategy

**Restart Policy:**

```javascript
class RestartPolicy {
  constructor() {
    this.strategies = {
      immediate: this.immediateRestart,
      exponential: this.exponentialBackoff,
      limited: this.limitedRestart
    };
    
    this.currentStrategy = 'exponential';
    this.restartDelay = 1000;  // Initial delay
    this.maxDelay = 60000;     // Max 1 minute
    this.restartCount = 0;
  }
  
  async restart(backend) {
    const strategy = this.strategies[this.currentStrategy];
    return strategy.call(this, backend);
  }
  
  async immediateRestart(backend) {
    await backend.restart();
  }
  
  async exponentialBackoff(backend) {
    const delay = Math.min(
      this.restartDelay * Math.pow(2, this.restartCount),
      this.maxDelay
    );
    
    console.log(`Restarting in ${delay}ms...`);
    await sleep(delay);
    await backend.restart();
    
    this.restartCount++;
  }
  
  async limitedRestart(backend) {
    const maxRestarts = 5;
    const window = 60000;  // 1 minute
    
    if (this.restartCount >= maxRestarts) {
      throw new Error('Max restarts reached');
    }
    
    await backend.restart();
    this.restartCount++;
    
    setTimeout(() => {
      this.restartCount = Math.max(0, this.restartCount - 1);
    }, window);
  }
  
  reset() {
    this.restartCount = 0;
    this.restartDelay = 1000;
  }
}

const restartPolicy = new RestartPolicy();
```

---

### Graceful Shutdown

**Shutdown Implementation:**

```javascript
async function gracefulShutdown() {
  console.log('Initiating graceful shutdown...');
  
  app.isQuitting = true;
  
  // 1. Hide all windows
  BrowserWindow.getAllWindows().forEach(window => {
    window.hide();
  });
  
  // 2. Stop crash detector
  crashDetector.stop();
  
  // 3. Request backend shutdown
  try {
    await fetch('http://localhost:5001/api/shutdown', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${authToken}`
      },
      timeout: 5000
    });
    
    // Wait for backend to exit
    await backend.waitForExit(10000);
  } catch (error) {
    console.warn('Graceful shutdown failed, forcing...');
    backend.forceKill();
  }
  
  // 4. Clean up PID file
  pidManager.cleanup();
  
  // 5. Quit app
  app.quit();
}

// Handle app quit
app.on('before-quit', (event) => {
  if (!app.isQuitting) {
    event.preventDefault();
    gracefulShutdown();
  }
});
```

---

## 🏥 HEALTH ENDPOINT STRATEGY

### Readiness Endpoints

**Endpoint Design:**

```python
# Backend: desktop_app.py

@app.route('/api/health/ready')
def health_ready():
    """
    Readiness check - is backend ready to serve requests?
    Returns 200 when fully initialized, 503 otherwise.
    """
    checks = {
        'database': _check_database(),
        'queue': _check_queue(),
        'workers': _check_workers(),
        'watchdog': _check_watchdog(),
        'health_monitor': _check_health_monitor()
    }
    
    all_ready = all(checks.values())
    
    return jsonify({
        'ready': all_ready,
        'checks': checks,
        'timestamp': datetime.now().isoformat()
    }), 200 if all_ready else 503

@app.route('/api/health/live')
def health_live():
    """
    Liveness check - is backend process alive?
    Returns 200 if process is running, regardless of readiness.
    """
    return jsonify({
        'alive': True,
        'timestamp': datetime.now().isoformat()
    }), 200

@app.route('/api/health/startup')
def health_startup():
    """
    Startup check - is backend still starting up?
    Returns 200 when startup complete, 503 during startup.
    """
    startup_complete = backend_state.get('startup_complete', False)
    
    return jsonify({
        'startup_complete': startup_complete,
        'timestamp': datetime.now().isoformat()
    }), 200 if startup_complete else 503
```

**Check Functions:**

```python
def _check_database():
    try:
        db.get_recent_logs(limit=1)
        return True
    except:
        return False

def _check_queue():
    try:
        qm.get_queue_stats()
        return True
    except:
        return False

def _check_workers():
    try:
        manager = wm.get_manager()
        return len(manager.workers) > 0
    except:
        return False

def _check_watchdog():
    try:
        watchdog = wd.get_watchdog()
        return watchdog.running
    except:
        return False

def _check_health_monitor():
    try:
        monitor = hm.get_monitor()
        return monitor.running
    except:
        return False
```

---

### Monitoring Endpoints

**Health Metrics:**

```python
@app.route('/api/health/metrics')
def health_metrics():
    """
    Detailed health metrics for monitoring.
    """
    try:
        monitor = hm.get_monitor()
        metrics = monitor.get_current_metrics()
        
        return jsonify({
            'status': 'healthy',
            'metrics': metrics,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/api/health/status')
def health_status():
    """
    Overall health status: healthy, degraded, or unhealthy.
    """
    try:
        monitor = hm.get_monitor()
        status = monitor.get_health_status()
        metrics = monitor.get_current_metrics()
        
        return jsonify({
            'status': status,
            'cpu_percent': metrics['cpu_percent'],
            'ram_percent': metrics['ram_percent'],
            'queue_depth': metrics['queue_depth'],
            'active_workers': metrics['active_workers'],
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500
```

---

### Timeout Handling

**Timeout Strategy:**

```javascript
async function fetchWithTimeout(url, options = {}) {
  const timeout = options.timeout || 5000;
  
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);
  
  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal
    });
    clearTimeout(timeoutId);
    return response;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') {
      throw new Error(`Request timeout after ${timeout}ms`);
    }
    throw error;
  }
}

// Usage
try {
  const response = await fetchWithTimeout('http://localhost:5001/api/health/ready', {
    timeout: 5000
  });
  const data = await response.json();
} catch (error) {
  console.error('Health check failed:', error.message);
}
```

---

### Degraded State Handling

**Degraded Mode:**

```python
@app.route('/api/health/degraded')
def health_degraded():
    """
    Check if system is in degraded state.
    Degraded = functional but with warnings.
    """
    warnings = []
    
    # Check CPU
    monitor = hm.get_monitor()
    metrics = monitor.get_current_metrics()
    
    if metrics['cpu_percent'] > 80:
        warnings.append('High CPU usage')
    
    if metrics['ram_percent'] > 80:
        warnings.append('High RAM usage')
    
    if metrics['queue_depth'] > 100:
        warnings.append('High queue depth')
    
    # Check Ollama
    if metrics.get('ollama_status') != 'running':
        warnings.append('Ollama offline')
    
    # Check workers
    manager = wm.get_manager()
    unhealthy = manager.check_health()
    if unhealthy:
        warnings.append(f'{len(unhealthy)} unhealthy workers')
    
    degraded = len(warnings) > 0
    
    return jsonify({
        'degraded': degraded,
        'warnings': warnings,
        'timestamp': datetime.now().isoformat()
    }), 200
```

**Electron Handling:**

```javascript
async function checkDegradedState() {
  try {
    const response = await fetch('http://localhost:5001/api/health/degraded');
    const data = await response.json();
    
    if (data.degraded) {
      // Show warning notification
      new Notification('SentinelAI - Warning', {
        body: `System degraded: ${data.warnings.join(', ')}`
      });
      
      // Update UI to show warning state
      updateUIState('degraded', data.warnings);
    } else {
      updateUIState('healthy');
    }
  } catch (error) {
    console.error('Degraded state check failed:', error);
  }
}

// Check every 30 seconds
setInterval(checkDegradedState, 30000);
```

---

### Failure State Handling

**Failure Detection:**

```python
@app.route('/api/health/failures')
def health_failures():
    """
    Get recent failures and errors.
    """
    try:
        # Get recent error logs
        logs = db.get_recent_logs(limit=100)
        errors = [log for log in logs if 'error' in log['event'].lower() or 'failed' in log['event'].lower()]
        
        # Get failed tasks
        failed_tasks = qm.list_tasks(status='failed', limit=10)
        
        # Get watchdog recovery count
        watchdog = wd.get_watchdog()
        recovery_count = watchdog.recovery_count
        
        return jsonify({
            'recent_errors': errors[:10],
            'failed_tasks': len(failed_tasks),
            'recovery_count': recovery_count,
            'timestamp': datetime.now().isoformat()
        }), 200
    except Exception as e:
        return jsonify({
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500
```

**Electron Handling:**

```javascript
async function checkFailures() {
  try {
    const response = await fetch('http://localhost:5001/api/health/failures');
    const data = await response.json();
    
    if (data.recent_errors.length > 5) {
      showWarning(`${data.recent_errors.length} recent errors detected`);
    }
    
    if (data.failed_tasks > 10) {
      showWarning(`${data.failed_tasks} failed tasks in queue`);
    }
    
    if (data.recovery_count > 10) {
      showWarning(`${data.recovery_count} automatic recoveries performed`);
    }
  } catch (error) {
    console.error('Failure check failed:', error);
  }
}
```

---

## 🔌 IPC + COMMUNICATION STRATEGY

### Electron IPC Usage

**IPC Channels:**

```javascript
// Main process
const { ipcMain } = require('electron');

// Backend control
ipcMain.on('restart-backend', async (event) => {
  try {
    await backend.restart();
    event.reply('backend-restarted', { success: true });
  } catch (error) {
    event.reply('backend-restarted', { success: false, error: error.message });
  }
});

ipcMain.on('stop-backend', async (event) => {
  try {
    await backend.stop();
    event.reply('backend-stopped', { success: true });
  } catch (error) {
    event.reply('backend-stopped', { success: false, error: error.message });
  }
});

// Window control
ipcMain.on('minimize-to-tray', (event) => {
  const window = BrowserWindow.fromWebContents(event.sender);
  window.hide();
});

ipcMain.on('quit-app', () => {
  gracefulShutdown();
});

// Notifications
ipcMain.on('show-notification', (event, { title, body }) => {
  new Notification({ title, body }).show();
});

// Backend status updates
function broadcastBackendStatus(status) {
  BrowserWindow.getAllWindows().forEach(window => {
    window.webContents.send('backend-status', status);
  });
}
```

**Preload Script:**

```javascript
// preload.js
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electron', {
  // Backend control
  restartBackend: () => ipcRenderer.send('restart-backend'),
  stopBackend: () => ipcRenderer.send('stop-backend'),
  
  // Window control
  minimizeToTray: () => ipcRenderer.send('minimize-to-tray'),
  quitApp: () => ipcRenderer.send('quit-app'),
  
  // Notifications
  notify: (title, body) => ipcRenderer.send('show-notification', { title, body }),
  
  // Events
  onBackendRestarted: (callback) => ipcRenderer.on('backend-restarted', (event, data) => callback(data)),
  onBackendStopped: (callback) => ipcRenderer.on('backend-stopped', (event, data) => callback(data)),
  onBackendStatus: (callback) => ipcRenderer.on('backend-status', (event, status) => callback(status))
});
```

---

### Local REST APIs

**API Communication:**

```javascript
// Frontend API client
class SentinelAPI {
  constructor(baseURL = 'http://localhost:5001') {
    this.baseURL = baseURL;
    this.authToken = localStorage.getItem('auth_token');
  }
  
  async request(endpoint, options = {}) {
    const url = `${this.baseURL}${endpoint}`;
    const headers = {
      'Content-Type': 'application/json',
      ...options.headers
    };
    
    if (this.authToken && options.auth !== false) {
      headers['Authorization'] = `Bearer ${this.authToken}`;
    }
    
    try {
      const response = await fetch(url, {
        ...options,
        headers,
        timeout: options.timeout || 10000
      });
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      return await response.json();
    } catch (error) {
      console.error(`API request failed: ${endpoint}`, error);
      throw error;
    }
  }
  
  // Convenience methods
  async get(endpoint, options = {}) {
    return this.request(endpoint, { ...options, method: 'GET' });
  }
  
  async post(endpoint, data, options = {}) {
    return this.request(endpoint, {
      ...options,
      method: 'POST',
      body: JSON.stringify(data)
    });
  }
  
  // Specific endpoints
  async getStatus() {
    return this.get('/api/status', { auth: false });
  }
  
  async getHealth() {
    return this.get('/api/system/health');
  }
  
  async getTasks() {
    return this.get('/api/tasks');
  }
  
  async approveTask(taskId) {
    return this.post(`/api/approve/${taskId}`);
  }
  
  async rejectTask(taskId) {
    return this.post(`/api/reject/${taskId}`);
  }
  
  async pause() {
    return this.post('/api/pause');
  }
  
  async resume() {
    return this.post('/api/resume');
  }
  
  async emergencyStop() {
    return this.post('/api/emergency-stop');
  }
}

// Global instance
const api = new SentinelAPI();
```

---

### WebSocket Strategy (Future)

**WebSocket Server (Backend):**

```python
# Future enhancement
from flask_socketio import SocketIO, emit

socketio = SocketIO(app, cors_allowed_origins="*")

@socketio.on('connect')
def handle_connect():
    emit('connected', {'message': 'Connected to SentinelAI'})

@socketio.on('subscribe')
def handle_subscribe(data):
    room = data.get('room')
    join_room(room)
    emit('subscribed', {'room': room})

# Broadcast events
def broadcast_task_update(task):
    socketio.emit('task_update', task, room='tasks')

def broadcast_health_update(health):
    socketio.emit('health_update', health, room='health')

def broadcast_log_event(log):
    socketio.emit('log_event', log, room='logs')
```

**WebSocket Client (Frontend):**

```javascript
// Future enhancement
class SentinelWebSocket {
  constructor(url = 'ws://localhost:5001') {
    this.url = url;
    this.socket = null;
    this.listeners = {};
  }
  
  connect() {
    this.socket = io(this.url);
    
    this.socket.on('connect', () => {
      console.log('WebSocket connected');
      this.emit('connected');
    });
    
    this.socket.on('disconnect', () => {
      console.log('WebSocket disconnected');
      this.emit('disconnected');
    });
    
    this.socket.on('task_update', (task) => {
      this.emit('task_update', task);
    });
    
    this.socket.on('health_update', (health) => {
      this.emit('health_update', health);
    });
    
    this.socket.on('log_event', (log) => {
      this.emit('log_event', log);
    });
  }
  
  subscribe(room) {
    this.socket.emit('subscribe', { room });
  }
  
  on(event, callback) {
    if (!this.listeners[event]) {
      this.listeners[event] = [];
    }
    this.listeners[event].push(callback);
  }
  
  emit(event, data) {
    if (this.listeners[event]) {
      this.listeners[event].forEach(callback => callback(data));
    }
  }
}

// Usage
const ws = new SentinelWebSocket();
ws.connect();
ws.subscribe('tasks');
ws.subscribe('health');

ws.on('task_update', (task) => {
  updateTaskUI(task);
});

ws.on('health_update', (health) => {
  updateHealthUI(health);
});
```

---

### Runtime Event Architecture

**Event System:**

```javascript
// Event bus for frontend
class EventBus {
  constructor() {
    this.listeners = {};
  }
  
  on(event, callback) {
    if (!this.listeners[event]) {
      this.listeners[event] = [];
    }
    this.listeners[event].push(callback);
  }
  
  off(event, callback) {
    if (this.listeners[event]) {
      this.listeners[event] = this.listeners[event].filter(cb => cb !== callback);
    }
  }
  
  emit(event, data) {
    if (this.listeners[event]) {
      this.listeners[event].forEach(callback => {
        try {
          callback(data);
        } catch (error) {
          console.error(`Event handler error for ${event}:`, error);
        }
      });
    }
  }
}

// Global event bus
const eventBus = new EventBus();

// Usage
eventBus.on('task:approved', (task) => {
  console.log('Task approved:', task);
  refreshTaskList();
});

eventBus.on('backend:unhealthy', () => {
  showWarning('Backend unhealthy');
});

eventBus.on('worker:failed', (worker) => {
  showNotification(`Worker ${worker.id} failed`);
});
```

---

### State Synchronization

**State Sync Strategy:**

```javascript
// Frontend state manager
class StateManager {
  constructor() {
    this.state = {
      backend: {
        running: false,
        paused: false,
        health: 'unknown'
      },
      tasks: [],
      workers: [],
      queue: {
        depth: 0,
        stats: {}
      },
      earnings: {
        confirmed: 0,
        pending: 0
      }
    };
    
    this.subscribers = [];
  }
  
  subscribe(callback) {
    this.subscribers.push(callback);
    return () => {
      this.subscribers = this.subscribers.filter(cb => cb !== callback);
    };
  }
  
  setState(updates) {
    this.state = {
      ...this.state,
      ...updates
    };
    
    this.notify();
  }
  
  notify() {
    this.subscribers.forEach(callback => {
      try {
        callback(this.state);
      } catch (error) {
        console.error('State subscriber error:', error);
      }
    });
  }
  
  async sync() {
    try {
      const [status, health, tasks, workers, queue, earnings] = await Promise.all([
        api.getStatus(),
        api.getHealth(),
        api.getTasks(),
        api.get('/api/system/workers'),
        api.get('/api/system/queue'),
        api.get('/api/earnings')
      ]);
      
      this.setState({
        backend: {
          running: status.running,
          paused: status.paused,
          health: health.status
        },
        tasks: tasks.tasks,
        workers: workers.workers,
        queue: queue.stats,
        earnings: earnings
      });
    } catch (error) {
      console.error('State sync failed:', error);
    }
  }
  
  startAutoSync(interval = 5000) {
    this.sync();  // Initial sync
    this.syncTimer = setInterval(() => this.sync(), interval);
  }
  
  stopAutoSync() {
    if (this.syncTimer) {
      clearInterval(this.syncTimer);
      this.syncTimer = null;
    }
  }
}

// Global state manager
const state = new StateManager();

// Usage
state.subscribe((newState) => {
  updateUI(newState);
});

state.startAutoSync(5000);  // Sync every 5 seconds
```

---

## 🎨 FUTURE UI MODULE STRATEGY

### Module Architecture

**Module Structure:**

```
desktop-shell/
├── src/
│   ├── modules/
│   │   ├── dashboard/
│   │   │   ├── Dashboard.jsx
│   │   │   ├── dashboard.css
│   │   │   └── index.js
│   │   ├── ai-chat/
│   │   │   ├── AIChat.jsx
│   │   │   ├── chat.css
│   │   │   └── index.js
│   │   ├── workers/
│   │   │   ├── Workers.jsx
│   │   │   ├── workers.css
│   │   │   └── index.js
│   │   ├── queue/
│   │   │   ├── Queue.jsx
│   │   │   ├── queue.css
│   │   │   └── index.js
│   │   ├── logs/
│   │   │   ├── Logs.jsx
│   │   │   ├── logs.css
│   │   │   └── index.js
│   │   ├── health/
│   │   │   ├── Health.jsx
│   │   │   ├── health.css
│   │   │   └── index.js
│   │   ├── sentinelweb/
│   │   │   ├── SentinelWeb.jsx
│   │   │   ├── sentinelweb.css
│   │   │   └── index.js
│   │   ├── guardian/
│   │   │   ├── Guardian.jsx
│   │   │   ├── guardian.css
│   │   │   └── index.js
│   │   ├── forge/
│   │   │   ├── Forge.jsx
│   │   │   ├── forge.css
│   │   │   └── index.js
│   │   ├── settings/
│   │   │   ├── Settings.jsx
│   │   │   ├── settings.css
│   │   │   └── index.js
│   │   └── emergency/
│   │       ├── Emergency.jsx
│   │       ├── emergency.css
│   │       └── index.js
│   ├── App.jsx
│   ├── Router.jsx
│   └── index.js
```

**Module Registration:**

```javascript
// src/modules/index.js
export const modules = [
  {
    id: 'dashboard',
    name: 'Dashboard',
    icon: 'dashboard',
    component: () => import('./dashboard'),
    route: '/',
    enabled: true
  },
  {
    id: 'ai-chat',
    name: 'AI Chat',
    icon: 'chat',
    component: () => import('./ai-chat'),
    route: '/chat',
    enabled: true
  },
  {
    id: 'workers',
    name: 'Workers',
    icon: 'workers',
    component: () => import('./workers'),
    route: '/workers',
    enabled: true
  },
  {
    id: 'queue',
    name: 'Queue',
    icon: 'queue',
    component: () => import('./queue'),
    route: '/queue',
    enabled: true
  },
  {
    id: 'logs',
    name: 'Logs',
    icon: 'logs',
    component: () => import('./logs'),
    route: '/logs',
    enabled: true
  },
  {
    id: 'health',
    name: 'Health',
    icon: 'health',
    component: () => import('./health'),
    route: '/health',
    enabled: true
  },
  {
    id: 'sentinelweb',
    name: 'SentinelWeb',
    icon: 'web',
    component: () => import('./sentinelweb'),
    route: '/sentinelweb',
    enabled: false  // Future
  },
  {
    id: 'guardian',
    name: 'Guardian',
    icon: 'shield',
    component: () => import('./guardian'),
    route: '/guardian',
    enabled: false  // Future
  },
  {
    id: 'forge',
    name: 'Forge',
    icon: 'build',
    component: () => import('./forge'),
    route: '/forge',
    enabled: false  // Future
  },
  {
    id: 'settings',
    name: 'Settings',
    icon: 'settings',
    component: () => import('./settings'),
    route: '/settings',
    enabled: true
  },
  {
    id: 'emergency',
    name: 'Emergency',
    icon: 'warning',
    component: () => import('./emergency'),
    route: '/emergency',
    enabled: true
  }
];
```

---

### Dashboard Module

**Purpose:** Main overview and control center

**Features:**
- System status overview
- Active tasks display
- Pending approvals
- Earnings summary
- Quick actions (pause/resume/emergency stop)
- Recent logs
- Health indicators

**API Endpoints Used:**
- `GET /api/status`
- `GET /api/tasks`
- `GET /api/pending-approvals`
- `GET /api/earnings`
- `GET /api/logs`
- `GET /api/system/health`
- `POST /api/pause`
- `POST /api/resume`
- `POST /api/emergency-stop`

---

### AI Chat Module

**Purpose:** Interactive AI assistant for SentinelAI control

**Features:**
- Natural language commands
- OpenClaw integration
- Command history
- Suggested actions
- Context-aware responses

**API Endpoints Used:**
- `POST /api/openclaw/command`
- `GET /api/openclaw/commands`

---

### Workers Module

**Purpose:** Worker management and monitoring

**Features:**
- Worker status display
- Worker health indicators
- Start/stop/pause/resume controls
- Worker statistics
- Task assignment view
- Restart individual workers

**API Endpoints Used:**
- `GET /api/system/workers`
- `POST /api/system/pause`
- `POST /api/system/resume`
- `POST /api/system/restart-workers`

---

### Queue Module

**Purpose:** Task queue management

**Features:**
- Queue depth visualization
- Task list (pending, running, completed, failed)
- Task details
- Task priority management
- Cancel tasks
- Retry failed tasks
- Queue statistics

**API Endpoints Used:**
- `GET /api/system/queue`
- `POST /api/queue/cancel/<id>` (future)
- `POST /api/queue/retry/<id>` (future)

---

### Logs Module

**Purpose:** System event logging and monitoring

**Features:**
- Real-time log stream
- Log filtering (by level, event type, time)
- Log search
- Export logs
- Log statistics

**API Endpoints Used:**
- `GET /api/logs`
- `GET /api/logs/filter` (future)
- `GET /api/logs/export` (future)

---

### Health Module

**Purpose:** System health monitoring and diagnostics

**Features:**
- CPU/RAM usage graphs
- Queue depth graph
- Worker health indicators
- System integrity check
- Watchdog status
- Health history
- Alert configuration

**API Endpoints Used:**
- `GET /api/system/health`
- `GET /api/system/health/summary`
- `GET /api/system/watchdog`
- `GET /api/system/integrity`

---

### SentinelWeb Module (Future)

**Purpose:** Web scraping and automation platform integration

**Features:**
- Web scraping tasks
- Automation workflows
- Data extraction
- Schedule management

**Status:** Placeholder for future integration

---

### Guardian Module (Future)

**Purpose:** Security monitoring and ethical hacking assistant

**Features:**
- Security scans
- Vulnerability detection
- Penetration testing
- Security reports

**Status:** Placeholder for future integration

---

### Forge Module (Future)

**Purpose:** Development tools and project builder

**Features:**
- Project scaffolding
- Code generation
- Build automation
- Deployment tools

**Status:** Placeholder for future integration

---

### Settings Module

**Purpose:** Application configuration

**Features:**
- Backend configuration
- Worker settings
- Queue settings
- Health thresholds
- Notification preferences
- API token management
- Theme selection

**API Endpoints Used:**
- `GET /api/settings` (future)
- `POST /api/settings` (future)

---

### Emergency Controls Module

**Purpose:** Emergency system controls

**Features:**
- Emergency stop button
- Force restart backend
- Clear queue
- Reset workers
- System diagnostics
- Recovery tools

**API Endpoints Used:**
- `POST /api/emergency-stop`
- `POST /api/system/restart-workers`
- `POST /api/queue/clear` (future)
- `POST /api/system/reset` (future)

---

## 🔒 SECURITY + SAFETY PRESERVATION

### Approval Systems

**CRITICAL:** All approval gates MUST be preserved in Electron implementation.

**Approval Flow:**

```javascript
// Frontend approval UI
async function approveTask(taskId) {
  // Show confirmation dialog
  const confirmed = await showConfirmDialog({
    title: 'Approve Task',
    message: 'Are you sure you want to approve this task for execution?',
    details: await getTaskDetails(taskId),
    buttons: ['Cancel', 'Approve']
  });
  
  if (!confirmed) return;
  
  try {
    await api.approveTask(taskId);
    showNotification('Task approved');
    refreshTaskList();
  } catch (error) {
    showError(`Failed to approve task: ${error.message}`);
  }
}

async function rejectTask(taskId) {
  const confirmed = await showConfirmDialog({
    title: 'Reject Task',
    message: 'Are you sure you want to reject this task?',
    buttons: ['Cancel', 'Reject']
  });
  
  if (!confirmed) return;
  
  try {
    await api.rejectTask(taskId);
    showNotification('Task rejected');
    refreshTaskList();
  } catch (error) {
    showError(`Failed to reject task: ${error.message}`);
  }
}
```

**Backend Enforcement:**

```python
# Backend MUST enforce approval
@app.route('/api/approve/<int:opp_id>', methods=['POST'])
def api_approve(opp_id):
    # Require authentication
    auth_token = request.headers.get('Authorization')
    if not verify_auth_token(auth_token):
        return jsonify({"error": "Unauthorized"}), 401
    
    # Update status to approved
    db.update_opportunity_status(opp_id, "approved")
    db.log_event("task_approved", f"Task #{opp_id} approved", opp_id)
    
    return jsonify({"status": "approved", "opportunity_id": opp_id})

# Executor MUST check approval before submission
def run_executor():
    opp = db.get_top_opportunity()
    
    # CRITICAL: Only execute approved tasks
    if opp['status'] != 'approved':
        logger.warning(f"Task #{opp['id']} not approved, skipping")
        return None
    
    # Proceed with execution...
```

---

### Dry-Run Protections

**CRITICAL:** Dry-run mode MUST be preserved.

**Dry-Run Configuration:**

```javascript
// Frontend dry-run toggle
async function toggleDryRun(enabled) {
  const confirmed = await showConfirmDialog({
    title: enabled ? 'Enable Dry-Run Mode' : 'Disable Dry-Run Mode',
    message: enabled 
      ? 'Dry-run mode prevents actual GitHub operations. Safe for testing.'
      : 'WARNING: Disabling dry-run will enable actual GitHub operations!',
    buttons: ['Cancel', enabled ? 'Enable' : 'Disable']
  });
  
  if (!confirmed) return;
  
  try {
    await api.post('/api/settings/dry-run', { enabled });
    showNotification(`Dry-run mode ${enabled ? 'enabled' : 'disabled'}`);
  } catch (error) {
    showError(`Failed to toggle dry-run: ${error.message}`);
  }
}
```

**Backend Enforcement:**

```python
# Backend MUST respect dry-run mode
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

def create_pull_request(owner, repo, branch, title, body, default_branch, dry_run=None):
    # Use global DRY_RUN if not specified
    if dry_run is None:
        dry_run = DRY_RUN
    
    if dry_run:
        url = f"https://github.com/{owner}/{repo}/pull/DRYRUN"
        logger.info(f"[DRY RUN] Would open PR: {url}")
        return url
    
    # Actual PR creation...
```

---

### Rollback Systems

**CRITICAL:** Rollback protection MUST be preserved.

**Rollback on Failure:**

```python
# In executor.py
try:
    # Apply patches
    patch_result = apply_patches_atomic(workspace, result)
    
    # Run tests
    post_patch_result = run_tests(workspace)
    
    # Check for regression
    if baseline_result.success and not post_patch_result.success:
        logger.error("Tests regressed after patch — rolling back")
        rollback_attempt(repo_obj, default_branch)
        db.update_opportunity_status(opp_id, "failed")
        cleanup_workspace(workspace)
        return None
    
except Exception as exc:
    logger.exception(f"Executor exception: {exc}")
    
    # Attempt rollback
    if repo_obj:
        rollback_attempt(repo_obj, default_branch)
    
    db.update_opportunity_status(opp_id, "failed")
    cleanup_workspace(workspace)
    return None
```

---

### Auth Boundaries

**CRITICAL:** Authentication MUST be enforced.

**Token Storage:**

```javascript
// Frontend token management
class AuthManager {
  constructor() {
    this.token = localStorage.getItem('auth_token');
  }
  
  setToken(token) {
    this.token = token;
    localStorage.setItem('auth_token', token);
  }
  
  getToken() {
    return this.token;
  }
  
  clearToken() {
    this.token = null;
    localStorage.removeItem('auth_token');
  }
  
  isAuthenticated() {
    return !!this.token;
  }
}

const auth = new AuthManager();
```

**Backend Validation:**

```python
# Backend MUST validate all protected endpoints
def verify_auth_token(token: str) -> bool:
    if not token:
        return False
    if token.startswith('Bearer '):
        token = token[7:]
    return token == AUTH_TOKEN

@app.route('/api/approve/<int:opp_id>', methods=['POST'])
def api_approve(opp_id):
    auth_token = request.headers.get('Authorization')
    if not verify_auth_token(auth_token):
        return jsonify({"error": "Unauthorized"}), 401
    
    # Proceed...
```

---

### Watchdog Systems

**CRITICAL:** Watchdog MUST continue monitoring.

**Watchdog Preservation:**

```python
# Watchdog MUST remain active
def start_backend():
    # ... other initialization ...
    
    # Start watchdog (CRITICAL)
    watchdog_interval = int(os.getenv("WATCHDOG_CHECK_INTERVAL", "30"))
    watchdog = wd.initialize_watchdog(watchdog_interval)
    watchdog.start()
    logger.info(f"Watchdog started (interval={watchdog_interval}s)")
```

**Electron Monitoring:**

```javascript
// Electron MUST NOT interfere with watchdog
// Watchdog runs in backend, Electron only monitors backend health
async function checkWatchdogStatus() {
  try {
    const response = await api.get('/api/system/watchdog');
    if (!response.running) {
      showWarning('Watchdog not running. System may not auto-recover.');
    }
  } catch (error) {
    console.error('Watchdog status check failed:', error);
  }
}
```

---

### Emergency Stop Systems

**CRITICAL:** Emergency stop MUST be accessible.

**Emergency Stop UI:**

```javascript
// Prominent emergency stop button
async function emergencyStop() {
  const confirmed = await showConfirmDialog({
    title: 'EMERGENCY STOP',
    message: 'This will immediately halt all operations. Are you sure?',
    buttons: ['Cancel', 'STOP'],
    type: 'warning'
  });
  
  if (!confirmed) return;
  
  try {
    await api.emergencyStop();
    showNotification('Emergency stop activated');
    
    // Update UI to show stopped state
    updateUIState('stopped');
  } catch (error) {
    showError(`Emergency stop failed: ${error.message}`);
  }
}

// Keyboard shortcut
document.addEventListener('keydown', (event) => {
  if (event.ctrlKey && event.shiftKey && event.key === 'X') {
    emergencyStop();
  }
});
```

**Backend Implementation:**

```python
@app.route('/api/emergency-stop', methods=['POST'])
def api_emergency_stop():
    auth_token = request.headers.get('Authorization')
    if not verify_auth_token(auth_token):
        return jsonify({"error": "Unauthorized"}), 401
    
    backend_state["running"] = False
    backend_state["paused"] = True
    
    # Stop all workers
    manager = wm.get_manager()
    manager.stop_all()
    
    logger.warning("EMERGENCY STOP activated")
    db.log_event("emergency_stop", "Emergency stop activated via API")
    
    return jsonify({"status": "stopped"})
```

---

### Local-Only Protections

**CRITICAL:** Localhost-only binding by default.

**Backend Binding:**

```python
# Backend MUST bind to localhost by default
def run_flask_app():
    host = os.getenv("FLASK_HOST", "127.0.0.1")  # Default: localhost only
    port = int(os.getenv("FLASK_PORT", "5001"))
    
    if host != "127.0.0.1":
        logger.warning(f"Binding to {host} - ensure firewall is configured!")
    
    app.run(host=host, port=port, debug=False, use_reloader=False)
```

**Electron Configuration:**

```javascript
// Electron MUST connect to localhost
const BACKEND_URL = 'http://127.0.0.1:5001';  // Hardcoded localhost

// Warn if backend is exposed
async function checkBackendExposure() {
  try {
    const response = await fetch(`${BACKEND_URL}/api/status`);
    const data = await response.json();
    
    // Check if backend is bound to 0.0.0.0
    if (data.host && data.host !== '127.0.0.1') {
      showWarning('Backend is exposed to network. Ensure firewall is configured.');
    }
  } catch (error) {
    // Ignore
  }
}
```

---

### Secret Isolation

**CRITICAL:** Secrets MUST NOT be exposed to frontend.

**Secret Handling:**

```python
# Backend MUST NOT expose secrets
@app.route('/api/config')
def api_config():
    # NEVER expose these
    sensitive_keys = [
        'GITHUB_TOKEN',
        'SENTINELAI_AUTH_TOKEN',
        'OPENAI_API_KEY',
        'DATABASE_PASSWORD'
    ]
    
    # Only expose safe config
    safe_config = {
        'max_workers': os.getenv('MAX_WORKERS', '3'),
        'scan_interval': os.getenv('SCAN_INTERVAL_HOURS', '2'),
        'dry_run': os.getenv('DRY_RUN', 'true'),
        'ollama_model': os.getenv('OLLAMA_MODEL', 'qwen2.5-coder:14b')
    }
    
    return jsonify(safe_config)
```

**Frontend Handling:**

```javascript
// Frontend MUST NOT store secrets
// Auth token is the ONLY secret stored (in localStorage)
// All other secrets remain in backend .env file

class SecureStorage {
  static setAuthToken(token) {
    localStorage.setItem('auth_token', token);
  }
  
  static getAuthToken() {
    return localStorage.getItem('auth_token');
  }
  
  static clearAuthToken() {
    localStorage.removeItem('auth_token');
  }
  
  // NEVER store these in frontend
  static FORBIDDEN_KEYS = [
    'github_token',
    'api_key',
    'password',
    'secret'
  ];
}
```

---

## 🚀 FUTURE SCALING STRATEGY

### Forge Integration

**Integration Plan:**

```
Forge Module
├── Backend API (Python)
│   ├── Project scaffolding
│   ├── Code generation
│   ├── Build automation
│   └── Deployment tools
├── Frontend UI (Electron)
│   ├── Project wizard
│   ├── Template selection
│   ├── Configuration editor
│   └── Build dashboard
└── Database Tables
    ├── forge_projects
    ├── forge_templates
    └── forge_builds
```

**API Endpoints:**
- `GET /api/forge/projects`
- `POST /api/forge/projects`
- `GET /api/forge/templates`
- `POST /api/forge/build/<id>`

---

### Guardian Integration

**Integration Plan:**

```
Guardian Module
├── Backend API (Python)
│   ├── Security scanning
│   ├── Vulnerability detection
│   ├── Penetration testing
│   └── Report generation
├── Frontend UI (Electron)
│   ├── Scan dashboard
│   ├── Vulnerability list
│   ├── Remediation guide
│   └── Security reports
└── Database Tables
    ├── guardian_scans
    ├── guardian_vulnerabilities
    └── guardian_reports
```

**API Endpoints:**
- `GET /api/guardian/scans`
- `POST /api/guardian/scan`
- `GET /api/guardian/vulnerabilities`
- `GET /api/guardian/reports/<id>`

---

### Android Companion Integration

**Integration Plan:**

```
Android App
├── React Native / Expo
├── REST API Client
├── Push Notifications
└── Features
    ├── System status
    ├── Task approvals
    ├── Emergency controls
    ├── Earnings tracking
    └── Notifications
```

**Communication:**
- Android → Backend: HTTP REST API
- Backend → Android: Push notifications (Firebase)
- Authentication: Same token-based auth

---

### Unified Command Center Vision

**Vision:**

```
┌─────────────────────────────────────────────────────────────┐
│              SENTINEL UNIFIED COMMAND CENTER                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │ Sentinel │  │ Sentinel │  │ Guardian │  │  Forge   │  │
│  │    AI    │  │   Web    │  │ Security │  │  Build   │  │
│  │  (Earn)  │  │ (Scrape) │  │  (Hack)  │  │  (Dev)   │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐  │
│  │           Unified Dashboard & Controls              │  │
│  │  - Cross-module task management                     │  │
│  │  - Unified logging and monitoring                   │  │
│  │  - Shared authentication                            │  │
│  │  - Integrated AI chat                               │  │
│  │  - Centralized settings                             │  │
│  └─────────────────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Features:**
- Single Electron app for all modules
- Unified authentication
- Cross-module task orchestration
- Shared logging and monitoring
- Integrated AI assistant
- Centralized configuration

---

### Distributed Runtime Possibilities

**Future Architecture:**

```
┌─────────────────────────────────────────────────────────────┐
│                  DISTRIBUTED SENTINEL                       │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   Machine 1  │  │   Machine 2  │  │   Machine 3  │    │
│  │              │  │              │  │              │    │
│  │  Workers 1-3 │  │  Workers 4-6 │  │  Workers 7-9 │    │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘    │
│         │                  │                  │             │
│         └──────────────────┼──────────────────┘             │
│                            │                                │
│                   ┌────────▼────────┐                      │
│                   │  Central Queue  │                      │
│                   │   (Redis/RMQ)   │                      │
│                   └────────┬────────┘                      │
│                            │                                │
│                   ┌────────▼────────┐                      │
│                   │ Central Database│                      │
│                   │  (PostgreSQL)   │                      │
│                   └─────────────────┘                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Requirements:**
- Replace SQLite with PostgreSQL
- Replace in-memory queue with Redis/RabbitMQ
- Implement distributed worker coordination
- Add load balancing
- Add failover support

---

### Multi-Machine Orchestration Possibilities

**Orchestration Strategy:**

```
Kubernetes Deployment
├── SentinelAI Backend (Deployment)
│   ├── Replicas: 3
│   ├── Auto-scaling: CPU >70%
│   └── Health checks: /api/health/ready
├── Worker Pool (StatefulSet)
│   ├── Replicas: 10
│   ├── Persistent volumes for workspaces
│   └── Anti-affinity rules
├── PostgreSQL (StatefulSet)
│   ├── Replicas: 3 (primary + 2 replicas)
│   └── Persistent volumes
├── Redis (Deployment)
│   ├── Replicas: 3 (cluster mode)
│   └── Persistent volumes
└── Ingress
    ├── HTTPS termination
    ├── Load balancing
    └── Rate limiting
```

**Benefits:**
- Horizontal scaling
- High availability
- Automatic failover
- Rolling updates
- Resource optimization

---

## 🎯 CONCLUSION

This document defines the **official architecture** for SentinelAI's future Electron desktop shell integration.

**Key Principles:**
1. **Backend Ownership** - Python backend owns all business logic
2. **Thin Client** - Electron shell is presentation layer only
3. **Safety First** - All safety systems MUST be preserved
4. **Modular Design** - Independent, testable modules
5. **Process Isolation** - Clear process boundaries
6. **Observability** - Comprehensive monitoring at all layers

**Implementation Readiness:**
- ✅ Backend architecture stable and production-ready
- ✅ API endpoints comprehensive and documented
- ✅ Safety systems validated and enforced
- ✅ Process management strategy defined
- ✅ Module architecture planned
- ✅ Future scaling strategy outlined

**Next Steps:**
1. Implement Electron main process
2. Implement backend process supervision
3. Create splash screen and launch flow
4. Implement dashboard module
5. Implement remaining core modules
6. Test integration thoroughly
7. Package and distribute

---

*End of Backend Integration Plan*

**SentinelAI v1.0.0** - Official Electron Integration Blueprint
