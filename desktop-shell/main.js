'use strict';

const { app, BrowserWindow, ipcMain, Menu, Notification } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const fetch = require('node-fetch');
const pty = require('node-pty');

// ============================================================================
// STARTUP DEBUG LOG
// ============================================================================
const _dbgLog = path.join(__dirname, '..', 'startup_debug.log');
function dbg(msg) {
  const line = `[${new Date().toISOString()}] ${msg}\n`;
  try { fs.appendFileSync(_dbgLog, line, 'utf8'); } catch (_) {}
  console.log(msg);
}
// Clear log on each launch
try { fs.writeFileSync(_dbgLog, '', 'utf8'); } catch (_) {}

// ============================================================================
// STATE
// ============================================================================

let orbWindow = null;          // Window 1 - The Orb
let workerWindow = null;        // Window 2 - Contextual worker windows (legacy, unused after panel system)
let logWindow = null;           // Log tab window (legacy)
let splashWindow = null;
let loginWindow = null;         // Login screen (first run / credential setup)
let setupWizardWindow = null;   // Setup wizard window (first run only)
let backendProcess = null;
let ptyProcess = null;          // Terminal PTY (legacy)
let backendReady = false;
let appReady = false;           // True once main windows have launched - guards window-all-closed
let isQuitting = false;
let isRestarting = false;

// Buffer for backend log lines captured before orb Socket.IO connects
const backendLogBuffer = [];

// Restart rate limiting — max 5 restarts within 60 s
const restartTimes = [];
const MAX_RESTARTS = 5;
const RESTART_WINDOW_MS = 60000;

// Configuration
const BACKEND_PORT = 5001;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const READINESS_TIMEOUT_MS = 90000;
const POLL_INTERVAL_MS = 500;
const HEALTH_CHECK_INTERVAL_MS = 10000;
const CONSECUTIVE_FAILURES_THRESHOLD = 3;

// PID file next to main.js for orphan prevention
const PID_FILE = path.join(__dirname, 'backend.pid');

// ============================================================================
// UTILITY
// ============================================================================

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function broadcastBackendStatus(payload) {
  if (orbWindow && !orbWindow.isDestroyed()) {
    orbWindow.webContents.send('backend-status', payload);
  }
  if (workerWindow && !workerWindow.isDestroyed()) {
    workerWindow.webContents.send('backend-status', payload);
  }
}

// ============================================================================
// SPLASH SCREEN
// ============================================================================

function createSplashScreen() {
  splashWindow = new BrowserWindow({
    width: 420,
    height: 280,
    frame: false,
    transparent: false,
    alwaysOnTop: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true
    },
    backgroundColor: '#000000'
  });

  // Minimal inline splash — does NOT load index.html (the Orchestration OS dashboard)
  // index.html is reserved for the explicit Orchestration OS window opened via menu.
  splashWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(`<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#000; color:#00ff88; font-family:'Segoe UI',sans-serif;
         display:flex; flex-direction:column; align-items:center; justify-content:center;
         height:100vh; gap:16px; }
  h1 { font-size:18px; letter-spacing:4px; color:#00ff88; text-shadow:0 0 12px #00ff88; }
  .sub { font-size:11px; letter-spacing:2px; color:#555; }
  .progress-wrap { width:260px; height:3px; background:rgba(0,255,136,.15); border-radius:2px; }
  .progress-bar { height:100%; background:#00ff88; border-radius:2px; transition:width .4s; box-shadow:0 0 8px #00ff88; }
  .msg { font-size:11px; color:#888; min-height:16px; }
</style></head>
<body>
  <h1>SENTINEL AI</h1>
  <span class="sub">INITIALIZING</span>
  <div class="progress-wrap"><div class="progress-bar" id="bar" style="width:5%"></div></div>
  <span class="msg" id="msg">Starting up...</span>
  <script>
    try {
      const {ipcRenderer} = require('electron');
      ipcRenderer.on('splash-progress', (_,v) => { document.getElementById('bar').style.width = v+'%'; });
      ipcRenderer.on('splash-message', (_,m) => { document.getElementById('msg').textContent = m; });
    } catch(_) {}
  </script>
</body></html>`)}`);
  splashWindow.center();
}

function updateSplash(message, progress) {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.webContents.send('splash-message', message);
    splashWindow.webContents.send('splash-progress', Math.max(0, Math.min(100, progress)));
  }
}

// ============================================================================
// PID MANAGEMENT
// ============================================================================

function writePID(pid) {
  try { fs.writeFileSync(PID_FILE, String(pid), 'utf8'); } catch (_) { /* ignore */ }
}

function readPID() {
  try { return parseInt(fs.readFileSync(PID_FILE, 'utf8'), 10); } catch (_) { return null; }
}

function clearPID() {
  try { fs.unlinkSync(PID_FILE); } catch (_) { /* ignore */ }
}

function isProcessRunning(pid) {
  try { process.kill(pid, 0); return true; } catch (_) { return false; }
}

function cleanupOrphanedBackend() {
  const pid = readPID();
  if (pid && isProcessRunning(pid)) {
    console.log(`[Orphan] Terminating leftover backend PID ${pid}`);
    try { process.kill(pid, 'SIGTERM'); } catch (_) { /* ignore */ }
  }
  clearPID();
}

// ============================================================================
// BACKEND PROCESS MANAGEMENT
// ============================================================================

function findPython() {
  // Prefer the project venv so all pip dependencies are available.
  // Fall back to system Python if venv is missing (e.g., first install before setup).
  const candidates = [
    // Project venv — preferred (Windows)
    path.join(__dirname, '..', 'venv', 'Scripts', 'python.exe'),
    // Project venv — preferred (Unix/macOS, keeps cross-platform compat)
    path.join(__dirname, '..', 'venv', 'bin', 'python'),
    // System Python fallbacks
    'python',
    'python3',
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python311', 'python.exe'),
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python310', 'python.exe'),
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'Python', 'Python39', 'python.exe'),
    'C:\\Python311\\python.exe',
    'C:\\Python310\\python.exe',
    'C:\\Python39\\python.exe',
  ];
  for (const candidate of candidates) {
    try {
      if (fs.existsSync(candidate)) {
        console.log(`[Python] Using: ${candidate}`);
        return candidate;
      }
    } catch (_) { /* continue */ }
  }
  // Last-resort: let the OS resolve it
  console.warn('[Python] venv not found — falling back to system python');
  return 'python';
}

// In a packaged install (NSIS), the bundled backend lives under
// process.resourcesPath/sentinel_backend/sentinel_backend.exe (configured in
// package.json extraResources). In dev we fall back to spawning Python on the
// source desktop_app.py so reloads remain instant.
function resolveBundledBackend() {
  if (!app.isPackaged) return null;
  const exePath = path.join(process.resourcesPath, 'sentinel_backend', 'sentinel_backend.exe');
  return fs.existsSync(exePath) ? exePath : null;
}

function launchBackend() {
  return new Promise((resolve, reject) => {
    const bundled = resolveBundledBackend();
    let command;
    let args;
    let backendDir;

    if (bundled) {
      command = bundled;
      args = [];
      backendDir = path.dirname(bundled);
      console.log('[Backend] Launching bundled backend...');
      console.log('[Backend] Exe:', bundled);
    } else {
      command = findPython();
      backendDir = path.join(__dirname, '..');
      args = [path.join(backendDir, 'desktop_app.py')];
      console.log('[Backend] Launching Python backend (dev mode)...');
      console.log('[Backend] Python:', command);
      console.log('[Backend] Script:', args[0]);
    }

    backendProcess = spawn(command, args, {
      cwd: backendDir,
      env: { ...process.env, SENTINEL_NO_BROWSER: '1' },
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,  // prevents terminal window appearing on Windows
      detached: false
    });

    if (!backendProcess.pid) {
      reject(new Error('Backend process failed to spawn (no PID)'));
      return;
    }

    writePID(backendProcess.pid);
    dbg(`[Backend] PID ${backendProcess.pid}`);

    backendProcess.stdout.on('data', (data) => {
      const lines = data.toString().split('\n').filter(l => l.trim());
      lines.forEach(line => {
        backendLogBuffer.push({
          type: 'system',
          level: 'info',
          message: line,
          timestamp: new Date().toISOString()
        });
        // Forward to orb if it's already open
        if (orbWindow && !orbWindow.isDestroyed()) {
          orbWindow.webContents.send('backend-log', {
            type: 'system', level: 'info', message: line,
            timestamp: new Date().toISOString()
          });
        }
      });
    });

    backendProcess.stderr.on('data', (data) => {
      const lines = data.toString().split('\n').filter(l => l.trim());
      lines.forEach(line => {
        const level = line.toLowerCase().includes('error') ? 'error' : 'info';
        backendLogBuffer.push({
          type: 'system',
          level,
          message: line,
          timestamp: new Date().toISOString()
        });
        if (orbWindow && !orbWindow.isDestroyed()) {
          orbWindow.webContents.send('backend-log', {
            type: 'system', level, message: line,
            timestamp: new Date().toISOString()
          });
        }
      });
    });

    backendProcess.on('exit', (code, signal) => {
      console.log(`[Backend] Exited — code=${code}, signal=${signal}`);
      clearPID();
      backendProcess = null;
      backendReady = false;

      // Only trigger crash handler if this was an unexpected exit
      if (!isQuitting && !isRestarting && code !== 0 && code !== null) {
        handleBackendCrash(code, signal);
      }
    });

    backendProcess.on('error', (error) => {
      console.error(`[Backend] Spawn error: ${error.message}`);
      reject(error);
    });

    // Give process 1 second to start, then resolve
    setTimeout(() => resolve(), 1000);
  });
}

function canRestart() {
  const now = Date.now();
  // Drop entries older than the window
  while (restartTimes.length > 0 && now - restartTimes[0] > RESTART_WINDOW_MS) {
    restartTimes.shift();
  }
  return restartTimes.length < MAX_RESTARTS;
}

async function restartBackend() {
  if (isRestarting || isQuitting) return;

  if (!canRestart()) {
    console.error('[Backend] Restart limit reached — manual intervention required');
    const { dialog } = require('electron');
    dialog.showErrorBox(
      'SentinelAI — Restart Limit Reached',
      `The backend has crashed ${MAX_RESTARTS} times in the last minute.\n\nPlease check your Python environment and restart the application manually.`
    );
    app.quit();
    return;
  }

  isRestarting = true;
  restartTimes.push(Date.now());
  const attempt = restartTimes.length;
  console.log(`[Backend] Restarting (attempt ${attempt}/${MAX_RESTARTS})...`);

  try {
    if (backendProcess) {
      backendProcess.kill('SIGTERM');
      await sleep(1500);
    }

    await launchBackend();
    await pollBackendReady();

    console.log('[Backend] Restart successful');
    broadcastBackendStatus({ status: 'running', message: 'Backend restarted successfully' });

    // No need to reload - orb window is static HTML
    if (orbWindow && !orbWindow.isDestroyed()) {
      orbWindow.webContents.send('backend-status', { status: 'running', message: 'Backend restarted' });
    }
  } catch (error) {
    console.error(`[Backend] Restart failed: ${error.message}`);
    broadcastBackendStatus({ status: 'error', message: `Restart failed: ${error.message}` });
  } finally {
    isRestarting = false;
  }
}

function handleBackendCrash(code, signal) {
  if (isQuitting) return;
  console.error(`[Backend] Crash — code=${code}, signal=${signal}`);
  broadcastBackendStatus({ status: 'crashed', message: `Backend crashed (exit code ${code})` });

  if (canRestart()) {
    console.log('[Backend] Scheduling auto-restart in 2 s...');
    setTimeout(() => restartBackend(), 2000);
  } else {
    const { dialog } = require('electron');
    dialog.showErrorBox(
      'SentinelAI Backend Crashed',
      `The backend crashed and cannot auto-recover.\n\nExit code: ${code}\n\nPlease restart the application.`
    );
    app.quit();
  }
}

function shutdownBackend() {
  return new Promise((resolve) => {
    if (!backendProcess) { resolve(); return; }

    console.log('[Backend] Sending SIGTERM...');

    const forceKill = setTimeout(() => {
      if (backendProcess && !backendProcess.killed) {
        console.log('[Backend] Force killing with SIGKILL...');
        backendProcess.kill('SIGKILL');
      }
    }, 5000);

    backendProcess.once('exit', () => {
      clearTimeout(forceKill);
      clearPID();
      console.log('[Backend] Shutdown complete');
      resolve();
    });

    backendProcess.kill('SIGTERM');
  });
}

// ============================================================================
// READINESS POLLING  (uses Node built-in http — avoids node-fetch quirks)
// ============================================================================

/**
 * Single HTTP GET using Node's built-in http module.
 * Returns the status code on success, or null on any connection error /
 * timeout.  Never throws.
 */
function httpGetStatus(url, timeoutMs = 1500) {
  return new Promise((resolve) => {
    const http = require('http');
    let settled = false;
    const settle = (v) => { if (!settled) { settled = true; resolve(v); } };

    try {
      const req = http.get(url, (res) => {
        // Drain the body so the socket can be reused
        res.on('data', () => {});
        res.on('end', () => settle(res.statusCode));
      });
      req.setTimeout(timeoutMs, () => { req.destroy(); settle(null); });
      req.on('error', () => settle(null));
    } catch (_) {
      settle(null);
    }
  });
}

async function pollBackendReady() {
  const startTime = Date.now();
  const deadline = startTime + READINESS_TIMEOUT_MS;
  let attempt = 0;

  while (Date.now() < deadline) {
    attempt++;
    const status = await httpGetStatus(`${BACKEND_URL}/api/ping`, 1500);

    if (status === 200) {
      console.log(`[Backend] Ready after ${attempt} poll(s) (${Date.now() - startTime} ms)`);
      backendReady = true;
      return true;
    }

    // Log non-200 (e.g. 500 during startup) but keep retrying
    if (status !== null) {
      console.warn(`[Backend] Poll ${attempt}: HTTP ${status} — retrying...`);
    }

    const elapsed = Date.now() - startTime;
    const progressPct = 40 + Math.min(40, Math.floor((elapsed / READINESS_TIMEOUT_MS) * 40));
    updateSplash(`Waiting for backend... (${attempt})`, progressPct);
    await sleep(POLL_INTERVAL_MS);
  }

  throw new Error(`Backend readiness timeout (${READINESS_TIMEOUT_MS / 1000} s)`);
}

async function existingBackendReady() {
  const status = await httpGetStatus(`${BACKEND_URL}/api/ping`, 2000);
  if (status === 200) {
    backendReady = true;
    console.log('[Backend] Reusing existing backend on port 5001');
    return true;
  }
  return false;
}

async function validateBackendHealth() {
  // Non-fatal — just log; use the fast ping probe
  const status = await httpGetStatus(`${BACKEND_URL}/api/ping`, 5000);
  if (status && status !== 200) {
    console.warn('[Health] /api/status returned HTTP', status);
  }
  return true;
}

// ============================================================================
// BACKEND SUPERVISION MONITOR
// ============================================================================

function startBackendMonitor() {
  let failures = 0;

  setInterval(async () => {
    if (!backendReady || isQuitting || isRestarting) return;

    const status = await httpGetStatus(`${BACKEND_URL}/api/ping`, 5000);
    if (status === 200) { failures = 0; return; }
    failures++;

    if (failures >= CONSECUTIVE_FAILURES_THRESHOLD) {
      console.error(`[Monitor] Backend unresponsive (${failures} consecutive failures) — restarting`);
      backendReady = false;
      failures = 0;
      restartBackend();
    } else {
      console.warn(`[Monitor] Health check failed (${failures}/${CONSECUTIVE_FAILURES_THRESHOLD})`);
    }
  }, HEALTH_CHECK_INTERVAL_MS);
}

// ============================================================================
// ORB WINDOW (Window 1 — Main persistent UI)
// ============================================================================

function createOrbWindow() {
  orbWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 1200,
    minHeight: 800,
    show: false,
    title: 'SentinelAI',
    frame: false,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    },
    backgroundColor: '#000000',
  });

  orbWindow.loadFile('orb.html');

  orbWindow.once('ready-to-show', () => {
    if (splashWindow && !splashWindow.isDestroyed()) {
      splashWindow.close();
      splashWindow = null;
    }
    if (orbWindow && !orbWindow.isDestroyed()) {
      orbWindow.show();
      orbWindow.focus();
    }
    appReady = true;
    console.log('[Orb] Window shown — appReady = true');
  });

  // Clicking X hides to tray instead of closing
  orbWindow.on('close', (event) => {
    if (!isQuitting) {
      event.preventDefault();
      orbWindow.hide();
    }
  });

  orbWindow.on('closed', () => { orbWindow = null; });
}

// ============================================================================
// WORKER WINDOW (Window 2 — Contextual worker UIs)
// ============================================================================

function createWorkerWindow(workerType = 'forge', context = {}) {
  // Close existing worker window if open
  if (workerWindow && !workerWindow.isDestroyed()) {
    workerWindow.close();
  }

  const windowMap = {
    earn: 'earn_window.html',
    market: 'market_window.html',
    guardian: 'guardian_window.html',
    scalp: 'scalp_window.html',
  };

  const htmlFile = windowMap[workerType] || windowMap['earn'];

  workerWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    minWidth: 900,
    minHeight: 600,
    show: true,
    title: `SentinelAI - ${workerType.charAt(0).toUpperCase() + workerType.slice(1)}`,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    },
    backgroundColor: '#0a0a0f'
  });

  workerWindow.loadFile(htmlFile);

  workerWindow.once('ready-to-show', () => {
    if (!workerWindow || workerWindow.isDestroyed()) return;
    workerWindow.show();
    workerWindow.focus();

    // Send context to the window
    if (Object.keys(context).length > 0) {
      workerWindow.webContents.send(`${workerType}-context`, context);
    }

    // (Forge window removed — Aider runs internally)
  });

  workerWindow.on('closed', () => {
    workerWindow = null;
    // Clean up any lingering PTY
    if (ptyProcess) {
      try { ptyProcess.kill(); } catch (_) {}
      ptyProcess = null;
    }
  });
}

// ============================================================================
// PTY TERMINAL (For Forge window)
// ============================================================================

function spawnPtyTerminal() {
  if (ptyProcess) {
    try { ptyProcess.kill(); } catch (_) {}
    ptyProcess = null;
  }

  const shell = process.platform === 'win32' ? 'powershell.exe' : 'bash';
  const cwd = path.join(__dirname, '..');

  try {
    ptyProcess = pty.spawn(shell, [], {
      name: 'xterm-color',
      cols: 80,
      rows: 24,
      cwd,
      env: process.env
    });

    ptyProcess.onData((data) => {
      if (workerWindow && !workerWindow.isDestroyed()) {
        workerWindow.webContents.send('terminal-output', data);
      }
    });

    ptyProcess.onExit((exitCode) => {
      console.log(`[PTY] Terminal exited with code ${exitCode.exitCode}`);
    });

    console.log('[PTY] Terminal spawned successfully');
  } catch (err) {
    console.error('[PTY] Failed to spawn terminal:', err.message);
  }
}

// ============================================================================
// ORCHESTRATION OS WINDOW (on-demand only, NOT shown on startup)
// ============================================================================

let orchestrationWindow = null;

function openOrchestrationOS() {
  if (orchestrationWindow && !orchestrationWindow.isDestroyed()) {
    orchestrationWindow.focus();
    return;
  }
  orchestrationWindow = new BrowserWindow({
    width: 1100,
    height: 750,
    title: 'SentinelAI — Orchestration OS',
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    },
    backgroundColor: '#0a0a0f'
  });
  orchestrationWindow.loadFile('index.html');
  orchestrationWindow.on('closed', () => { orchestrationWindow = null; });
}

// ============================================================================
// SETUP WIZARD
// ============================================================================

function getEnvPath() {
  // Packaged app: write to resources dir (writable, outside asar)
  // Dev mode: write to project root
  return app.isPackaged
    ? path.join(process.resourcesPath, '.env')
    : path.join(__dirname, '..', '.env');
}

function isFirstRun() {
  return !fs.existsSync(getEnvPath());
}

// ---------------------------------------------------------------------------
// VITALS CHECK — only 3 things block startup; everything else is lazy
// ---------------------------------------------------------------------------
async function ensureEnvFile() {
  const envPath = getEnvPath();
  if (fs.existsSync(envPath)) return;

  console.log('[Startup] .env not found — creating empty one');
  const examplePath = path.join(__dirname, '..', '.env.example');
  if (fs.existsSync(examplePath)) {
    fs.copyFileSync(examplePath, envPath);
  } else {
    fs.writeFileSync(envPath, '# SentinelAI configuration\n', 'utf8');
  }
}

async function checkOllamaRunning() {
  // Use 127.0.0.1 explicitly — on Windows, 'localhost' can resolve to ::1 (IPv6)
  // but Ollama binds to 127.0.0.1 (IPv4), causing immediate ECONNREFUSED.
  const status = await httpGetStatus('http://127.0.0.1:11434/api/tags', 3000);
  return status === 200;
}

async function vitalsCheck() {
  const { dialog } = require('electron');

  // CHECK 1: Ollama
  dbg('[Vitals] Checking Ollama...');
  let ollamaOk = await checkOllamaRunning();
  dbg(`[Vitals] Ollama check result: ${ollamaOk}`);
  if (!ollamaOk) {
    dbg('[Vitals] Showing Ollama dialog...');
    // Show dialog and poll until Ollama responds
    dialog.showMessageBoxSync({
      type: 'warning',
      title: 'Ollama Not Running',
      message: 'Ollama is not running.\n\nStart it with:  ollama serve\n\nClick OK once Ollama is running.',
      buttons: ['OK — I started it']
    });
    // Poll for up to 60s
    const deadline = Date.now() + 60000;
    while (Date.now() < deadline) {
      await sleep(3000);
      if (await checkOllamaRunning()) { ollamaOk = true; break; }
    }
    if (!ollamaOk) {
      dbg('[Vitals] Ollama still not reachable — continuing anyway');
      console.warn('[Vitals] Ollama still not reachable — continuing anyway');
    }
  }

  dbg('[Vitals] Checking venv Python...');
  // CHECK 2: venv Python
  const venvPy = path.join(__dirname, '..', 'venv', 'Scripts', 'python.exe');
  if (!fs.existsSync(venvPy)) {
    dialog.showMessageBoxSync({
      type: 'error',
      title: 'Python venv Not Found',
      message: 'Python virtual environment not found.\n\nRun these commands in the SentinelAI folder:\n\n  python -m venv venv\n  venv\\Scripts\\activate\n  pip install -r requirements.txt\n\nThen restart SentinelAI.',
      buttons: ['OK']
    });
    app.quit();
    return false;
  }

  return true;
}

// createSetupWizardWindow kept for reference but no longer called on first run
function createSetupWizardWindow() {
  setupWizardWindow = new BrowserWindow({
    width: 800,
    height: 900,
    title: 'SentinelAI Setup',
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true
    }
  });
  if (fs.existsSync(path.join(__dirname, 'setup_wizard.html'))) {
    setupWizardWindow.loadFile(path.join(__dirname, 'setup_wizard.html'));
    setupWizardWindow.show();
  }
  setupWizardWindow.on('closed', () => { setupWizardWindow = null; });
  return setupWizardWindow;
}

// ============================================================================
// IPC HANDLERS
// ============================================================================

function setupIPC() {
  // Return buffered backend log lines and clear the buffer
  ipcMain.handle('get-log-buffer', () => {
    const buffer = [...backendLogBuffer];
    backendLogBuffer.length = 0;
    return buffer;
  });

  // Open a panel inside the orb window (replaces separate worker windows)
  ipcMain.on('open-panel', (event, panelName) => {
    if (orbWindow && !orbWindow.isDestroyed()) {
      orbWindow.webContents.send('open-panel', panelName);
    }
  });

  // Route to a specific worker window (legacy — now sends open-panel to orb)
  ipcMain.on('route-to-worker', (event, { worker, context }) => {
    dbg(`[IPC] Routing to panel: ${worker}`);
    if (orbWindow && !orbWindow.isDestroyed()) {
      orbWindow.webContents.send('open-panel', worker);
    }
  });

  // Terminal I/O for Forge window (node-pty integration will be added in Track 3)
  ipcMain.on('terminal-input', (event, data) => {
    if (ptyProcess) {
      try {
        ptyProcess.write(data);
      } catch (err) {
        console.error('[PTY] Write error:', err.message);
      }
    }
  });

  ipcMain.on('restart-backend', async (event) => {
    console.log('[IPC] restart-backend');
    await restartBackend();
    if (!event.sender.isDestroyed()) {
      event.reply('backend-restarted', { success: backendReady });
    }
  });

  ipcMain.on('minimize-window', (event) => {
    const win = BrowserWindow.fromWebContents(event.sender);
    if (win) win.hide();
  });

  ipcMain.on('quit-app', () => {
    gracefulShutdown();
  });

  ipcMain.on('open-orchestration-os', () => {
    openOrchestrationOS();
  });

  ipcMain.on('open-log', () => {
    if (orbWindow && !orbWindow.isDestroyed()) {
      orbWindow.webContents.send('open-panel', 'log');
    }
  });

  ipcMain.on('open-forge', () => {
    new Notification({
      title: 'Forge Integrated',
      body: 'Forge is now built into Sentinel. Just ask Sentinel to build something.',
    }).show();
  });

  ipcMain.on('show-notification', (_event, { title, body }) => {
    new Notification({ title, body }).show();
  });

  // Setup wizard completion
  ipcMain.on('setup-complete', async (event, config) => {
    console.log('[Wizard] setup-complete received');

    // Step 1: write .env (do NOT abort launch if this fails — user can fix later)
    const envContent = Object.entries(config)
      .filter(([_, v]) => v !== null && v !== undefined && v !== '')
      .map(([k, v]) => {
        const key = k.toUpperCase();
        const value = typeof v === 'boolean' ? (v ? 'true' : 'false') : v;
        return `${key}=${value}`;
      })
      .join('\n');

    const envPath = getEnvPath();
    try {
      fs.writeFileSync(envPath, envContent, 'utf8');
      console.log('[Wizard] .env written to', envPath);
    } catch (err) {
      console.error('[Wizard] .env write failed:', err.message);
      // Continue anyway — main windows must still launch
    }

    // Step 2: launch main windows BEFORE closing the wizard.
    // This ensures `window-all-closed` never fires with zero windows
    // (which would trigger gracefulShutdown and kill the app).
    console.log('[Wizard] Creating orb window...');
    createOrbWindow();
    startBackendMonitor();

    // Step 3: close the wizard now that the main windows exist
    if (setupWizardWindow && !setupWizardWindow.isDestroyed()) {
      console.log('[Wizard] Closing wizard window');
      setupWizardWindow.close();
    }

    console.log('[Wizard] Launch complete');
  });
}

// ============================================================================
// LOG WINDOW (legacy — now inline panel)
// ============================================================================

function openLogWindow() {
  // Log is now an inline panel — open it in the orb
  if (orbWindow && !orbWindow.isDestroyed()) {
    orbWindow.webContents.send('open-panel', 'log');
  }
}

// ============================================================================
// LOGIN WINDOW
// ============================================================================

function checkLoginConfigured() {
  return new Promise((resolve) => {
    const http = require('http');
    let data = '';
    const req = http.get(`http://127.0.0.1:${BACKEND_PORT}/api/login/status`, (res) => {
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try {
          const status = JSON.parse(data);
          resolve(status.configured === true);
        } catch (_) { resolve(false); }
      });
    });
    req.setTimeout(3000, () => { req.destroy(); resolve(false); });
    req.on('error', () => resolve(false));
  });
}

function createLoginWindow() {
  return new Promise((resolve) => {
    loginWindow = new BrowserWindow({
      width: 560,
      height: 750,
      minWidth: 480,
      minHeight: 600,
      title: 'SentinelAI — Connect',
      frame: false,
      resizable: true,
      webPreferences: {
        nodeIntegration: true,
        contextIsolation: false,
      },
      backgroundColor: '#000000',
    });

    loginWindow.loadFile(path.join(__dirname, 'login_window.html'));
    loginWindow.once('ready-to-show', () => {
      if (splashWindow && !splashWindow.isDestroyed()) {
        splashWindow.close(); splashWindow = null;
      }
      loginWindow.show();
      loginWindow.focus();
    });

    // When user completes login, close this window and launch orb
    ipcMain.once('login-complete', () => {
      if (loginWindow && !loginWindow.isDestroyed()) loginWindow.close();
      loginWindow = null;
      resolve();
    });

    // Allow skipping login by closing window
    loginWindow.on('closed', () => {
      loginWindow = null;
      resolve();
    });
  });
}

// ============================================================================
// APP MENU
// ============================================================================

function buildAppMenu() {
  const template = [
    {
      label: 'Platforms',
      submenu: [
        {
          label: 'Earn',
          accelerator: 'CmdOrCtrl+1',
          click: () => { if (orbWindow && !orbWindow.isDestroyed()) orbWindow.webContents.send('open-panel', 'earn'); }
        },
        {
          label: 'Market',
          accelerator: 'CmdOrCtrl+2',
          click: () => { if (orbWindow && !orbWindow.isDestroyed()) orbWindow.webContents.send('open-panel', 'market'); }
        },
        {
          label: 'Guardian',
          accelerator: 'CmdOrCtrl+3',
          click: () => { if (orbWindow && !orbWindow.isDestroyed()) orbWindow.webContents.send('open-panel', 'guardian'); }
        },
        {
          label: 'Scalp',
          accelerator: 'CmdOrCtrl+4',
          click: () => { if (orbWindow && !orbWindow.isDestroyed()) orbWindow.webContents.send('open-panel', 'scalp'); }
        },
        { type: 'separator' },
        {
          label: 'Log',
          accelerator: 'CmdOrCtrl+L',
          click: () => { if (orbWindow && !orbWindow.isDestroyed()) orbWindow.webContents.send('open-panel', 'log'); }
        }
      ]
    },
    {
      label: 'Tools',
      submenu: [
        {
          label: 'Orchestration OS',
          accelerator: 'CmdOrCtrl+O',
          click: () => openOrchestrationOS()
        }
      ]
    },
    {
      label: 'Window',
      submenu: [
        { role: 'minimize' },
        { role: 'close' }
      ]
    }
  ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

// ============================================================================
// STARTUP SEQUENCE
// ============================================================================

async function startupSequence() {
  try {
    dbg('[Startup] startupSequence BEGIN');
    cleanupOrphanedBackend();

    createSplashScreen();
    updateSplash('Initializing SentinelAI...', 5);
    await sleep(300); // Let splash render

    // Vitals: Ollama + venv check (lazy .env creation)
    dbg('[Startup] Running vitalsCheck...');
    updateSplash('Checking system vitals...', 8);
    const vitalsOk = await vitalsCheck();
    dbg(`[Startup] vitalsCheck returned: ${vitalsOk}`);
    if (!vitalsOk) return; // app.quit() already called

    dbg('[Startup] Checking for existing backend...');
    updateSplash('Checking backend...', 15);
    const reusedBackend = await existingBackendReady();
    dbg(`[Startup] existingBackendReady: ${reusedBackend}`);
    if (!reusedBackend) {
      dbg('[Startup] Launching backend...');
      updateSplash('Starting Python backend...', 15);
      await launchBackend();
      dbg('[Startup] launchBackend complete, polling...');

      updateSplash('Waiting for backend...', 35);
      await pollBackendReady();
      dbg('[Startup] pollBackendReady complete');
    }

    updateSplash('Validating runtime health...', 82);
    await validateBackendHealth();

    updateSplash('Checking identity...', 88);
    const loggedIn = await checkLoginConfigured();
    dbg(`[Startup] Login configured: ${loggedIn}`);

    updateSplash('Opening dashboard...', 92);

    // First-run: ensure .env exists (create empty from .env.example if needed)
    await ensureEnvFile();

    if (!loggedIn) {
      dbg('[Startup] Showing login screen...');
      updateSplash('First run — connect your accounts...', 95);
      await createLoginWindow();
      dbg('[Startup] Login screen closed — opening orb');
    }

    dbg('[Startup] Creating orb window...');
    createOrbWindow();
    startBackendMonitor();

    updateSplash('Ready!', 100);
    dbg('[Startup] Complete — SentinelAI is running');
    console.log('[Startup] Complete — SentinelAI is running');
  } catch (error) {
    console.error('[Startup] Fatal error:', error.message);

    const { dialog } = require('electron');
    await shutdownBackend();
    dialog.showErrorBox(
      'SentinelAI Startup Failed',
      `Could not start SentinelAI:\n\n${error.message}\n\nCheck that:\n• Python 3.8+ is installed\n• pip dependencies are installed (pip install -r requirements.txt)\n• Port ${BACKEND_PORT} is not already in use`
    );
    app.quit();
  }
}

// ============================================================================
// GRACEFUL SHUTDOWN
// ============================================================================

async function gracefulShutdown() {
  if (isQuitting) return;
  isQuitting = true;
  console.log('[Shutdown] Graceful shutdown initiated');

  BrowserWindow.getAllWindows().forEach(win => {
    if (!win.isDestroyed()) win.hide();
  });

  await shutdownBackend();
  app.exit(0);
}

// ============================================================================
// APP LIFECYCLE
// ============================================================================

app.whenReady().then(() => {
  setupIPC();
  buildAppMenu();
  startupSequence();

  app.on('activate', () => {
    // macOS: re-show window when dock icon clicked
    if (orbWindow && !orbWindow.isDestroyed()) {
      orbWindow.show();
    } else if (BrowserWindow.getAllWindows().length === 0 && backendReady) {
      createOrbWindow();
      createWorkerWindow('forge');
    }
  });
});

app.on('window-all-closed', () => {
  // Guard against wizard-to-orb transition: if the wizard window closes
  // before createOrbWindow's ready-to-show fires, this would otherwise quit
  // the app. appReady flips to true once the orb is shown.
  if (!appReady) {
    console.log('[App] window-all-closed fired before appReady — ignoring to allow wizard transition');
    return;
  }
  if (process.platform !== 'darwin') {
    gracefulShutdown();
  }
});

app.on('before-quit', (event) => {
  if (!isQuitting) {
    event.preventDefault();
    gracefulShutdown();
  }
});

// Ensure backend is cleaned up on unexpected Node exit
process.on('exit', () => { clearPID(); });
process.on('SIGINT', () => gracefulShutdown());
process.on('SIGTERM', () => gracefulShutdown());
