'use strict';

const { app, BrowserWindow, ipcMain, Notification } = require('electron');
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const fetch = require('node-fetch');
const pty = require('node-pty');

// ============================================================================
// STATE
// ============================================================================

let orbWindow = null;          // Window 1 - The Orb
let workerWindow = null;        // Window 2 - Contextual worker windows
let splashWindow = null;
let backendProcess = null;
let ptyProcess = null;          // Terminal PTY for Forge window
let backendReady = false;
let isQuitting = false;
let isRestarting = false;

// Restart rate limiting — max 5 restarts within 60 s
const restartTimes = [];
const MAX_RESTARTS = 5;
const RESTART_WINDOW_MS = 60000;

// Configuration
const BACKEND_PORT = 5001;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const READINESS_TIMEOUT_MS = 30000;
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
    width: 460,
    height: 340,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    }
  });
  // Splash uses a minimal loading screen (we'll keep index.html as splash for now)
  splashWindow.loadFile('index.html');
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
  // Common Python paths on Windows — return first that exists
  const candidates = [
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
      if (!candidate.includes(path.sep) || fs.existsSync(candidate)) return candidate;
    } catch (_) { /* continue */ }
  }
  return 'python';
}

function launchBackend() {
  return new Promise((resolve, reject) => {
    const pythonPath = findPython();
    const backendDir = path.join(__dirname, '..');
    const scriptPath = path.join(backendDir, 'desktop_app.py');

    console.log('[Backend] Launching Python backend...');
    console.log('[Backend] Python:', pythonPath);
    console.log('[Backend] Script:', scriptPath);

    backendProcess = spawn(pythonPath, [scriptPath], {
      cwd: backendDir,
      env: { ...process.env },
      stdio: ['ignore', 'pipe', 'pipe'],
      detached: false
    });

    if (!backendProcess.pid) {
      reject(new Error('Backend process failed to spawn (no PID)'));
      return;
    }

    writePID(backendProcess.pid);
    console.log(`[Backend] PID ${backendProcess.pid}`);

    backendProcess.stdout.on('data', (data) => {
      const lines = data.toString().trim().split('\n');
      lines.forEach(line => { if (line) console.log(`[Backend] ${line}`); });
    });

    backendProcess.stderr.on('data', (data) => {
      const lines = data.toString().trim().split('\n');
      lines.forEach(line => { if (line) console.error(`[Backend ERR] ${line}`); });
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
// READINESS POLLING
// ============================================================================

async function pollBackendReady() {
  const deadline = Date.now() + READINESS_TIMEOUT_MS;
  let attempt = 0;

  while (Date.now() < deadline) {
    attempt++;
    try {
      const response = await fetch(`${BACKEND_URL}/api/status`, { timeout: 2000 });
      if (response.ok) {
        console.log(`[Backend] Ready after ${attempt} poll(s)`);
        backendReady = true;
        return true;
      }
    } catch (_) {
      // Not ready yet
    }

    const elapsed = Date.now() + READINESS_TIMEOUT_MS - deadline;
    const progressPct = 40 + Math.min(40, Math.floor((elapsed / READINESS_TIMEOUT_MS) * 40));
    updateSplash(`Waiting for backend... (${attempt})`, progressPct);
    await sleep(POLL_INTERVAL_MS);
  }

  throw new Error('Backend readiness timeout (30 s)');
}

async function existingBackendReady() {
  try {
    const response = await fetch(`${BACKEND_URL}/api/status`, { timeout: 2000 });
    if (!response.ok) return false;
    backendReady = true;
    console.log('[Backend] Reusing existing backend on port 5001');
    return true;
  } catch (_) {
    return false;
  }
}

async function validateBackendHealth() {
  try {
    const response = await fetch(`${BACKEND_URL}/api/system/health`, { timeout: 5000 });
    if (!response.ok) return true; // Non-fatal
    const health = await response.json();
    if ((health.cpu_percent || 0) > 85) console.warn('[Health] High CPU:', health.cpu_percent);
    if ((health.ram_percent || 0) > 85) console.warn('[Health] High RAM:', health.ram_percent);
  } catch (_) {
    // Health check is non-fatal during startup
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

    try {
      const response = await fetch(`${BACKEND_URL}/api/status`, { timeout: 5000 });
      if (response.ok) { failures = 0; return; }
      failures++;
    } catch (_) {
      failures++;
    }

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
    width: 800,
    height: 700,
    minWidth: 600,
    minHeight: 500,
    show: false,
    title: 'SentinelAI',
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    },
    backgroundColor: '#0a0a0f',
    frame: true
  });

  orbWindow.loadFile('orb.html');

  orbWindow.once('ready-to-show', () => {
    if (splashWindow && !splashWindow.isDestroyed()) {
      splashWindow.close();
      splashWindow = null;
    }
    orbWindow.show();
    orbWindow.focus();
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
    forge: 'forge_window.html',
    earn: 'earn_window.html',
    market: 'market_window.html',
    guardian: 'guardian_window.html'
  };

  const htmlFile = windowMap[workerType] || windowMap['forge'];

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
    workerWindow.show();
    workerWindow.focus();

    // Send context to the window
    if (Object.keys(context).length > 0) {
      workerWindow.webContents.send(`${workerType}-context`, context);
    }

    // If this is Forge, spawn a PTY terminal
    if (workerType === 'forge') {
      spawnPtyTerminal();
    }
  });

  workerWindow.on('closed', () => {
    workerWindow = null;
    // Clean up PTY if this was a Forge window
    if (ptyProcess && workerType === 'forge') {
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
// SETUP WIZARD
// ============================================================================

function isFirstRun() {
  // Check if .env file exists in parent directory
  const envPath = path.join(__dirname, '..', '.env');
  return !fs.existsSync(envPath);
}

function createSetupWizardWindow() {
  const setupWindow = new BrowserWindow({
    width: 800,
    height: 900,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true
    }
  });

  setupWindow.loadFile(path.join(__dirname, 'setup_wizard.html'));
  setupWindow.show();

  return setupWindow;
}

// ============================================================================
// IPC HANDLERS
// ============================================================================

function setupIPC() {
  // Route to a specific worker window
  ipcMain.on('route-to-worker', (event, { worker, context }) => {
    console.log(`[IPC] Routing to worker: ${worker}`);
    createWorkerWindow(worker, context);
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

  ipcMain.on('show-notification', (_event, { title, body }) => {
    new Notification({ title, body }).show();
  });

  // Setup wizard completion
  ipcMain.on('setup-complete', (event, config) => {
    console.log('[IPC] Setup wizard completed - writing .env');

    // Convert config to .env format
    const envContent = Object.entries(config)
      .filter(([_, v]) => v !== null && v !== undefined && v !== '')
      .map(([k, v]) => {
        const key = k.toUpperCase();
        const value = typeof v === 'boolean' ? (v ? 'true' : 'false') : v;
        return `${key}=${value}`;
      })
      .join('\n');

    // Write .env file
    const envPath = path.join(__dirname, '..', '.env');
    try {
      fs.writeFileSync(envPath, envContent, 'utf8');
      console.log('[IPC] .env file written successfully');

      // Close setup window and launch main windows
      const setupWin = BrowserWindow.fromWebContents(event.sender);
      if (setupWin && !setupWin.isDestroyed()) {
        setupWin.close();
      }

      // Launch main windows after small delay
      setTimeout(() => {
        createOrbWindow();
        createWorkerWindow('forge');
        startBackendMonitor();
      }, 500);
    } catch (err) {
      console.error('[IPC] Failed to write .env:', err);
      event.reply('setup-error', { error: err.message });
    }
  });
}

// ============================================================================
// STARTUP SEQUENCE
// ============================================================================

async function startupSequence() {
  try {
    cleanupOrphanedBackend();

    createSplashScreen();
    updateSplash('Initializing SentinelAI...', 5);
    await sleep(300); // Let splash render

    updateSplash('Checking backend...', 15);
    const reusedBackend = await existingBackendReady();
    if (!reusedBackend) {
      updateSplash('Starting Python backend...', 15);
      await launchBackend();

      updateSplash('Waiting for backend...', 35);
      await pollBackendReady();
    }

    updateSplash('Validating runtime health...', 82);
    await validateBackendHealth();

    updateSplash('Opening dashboard...', 92);

    // Check if first run - show setup wizard
    if (isFirstRun()) {
      console.log('[Startup] First run detected - launching setup wizard');
      updateSplash('First-run setup...', 95);
      splashWindow.hide();
      createSetupWizardWindow();
      return; // Don't launch main windows yet
    }

    // Launch BOTH windows on startup
    createOrbWindow();           // Window 1 - The Orb (persistent)
    createWorkerWindow('forge'); // Window 2 - Default to Forge dashboard

    startBackendMonitor();

    updateSplash('Ready!', 100);
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
  // On non-macOS this only fires when windows are truly closed (not hidden)
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
