'use strict';

const { contextBridge, ipcRenderer } = require('electron');

// Auth token comes from the main process via process.env (injected before
// the BrowserWindow loads). The renderer never sees the file path — only the
// token value, surfaced as window.__SENTINEL_AUTH__ by the shim below.
const __SENTINEL_AUTH__ = process.env.SENTINELAI_AUTH_TOKEN || '';

contextBridge.exposeInMainWorld('sentinelAuth', {
  token: __SENTINEL_AUTH__,
});

contextBridge.exposeInMainWorld('electronAPI', {
  // Backend status events
  onBackendStatus: (callback) => {
    ipcRenderer.on('backend-status', (_event, status) => callback(status));
  },

  // Backend control
  restartBackend: () => ipcRenderer.send('restart-backend'),
  onBackendRestarted: (callback) => {
    ipcRenderer.on('backend-restarted', (_event, data) => callback(data));
  },

  // Window control
  minimizeToTray: () => ipcRenderer.send('minimize-window'),
  quitApp: () => ipcRenderer.send('quit-app'),

  // Desktop notifications
  notify: (title, body) => ipcRenderer.send('show-notification', { title, body }),

  // Setup wizard
  submitSetup: (config) => ipcRenderer.send('setup-complete', config),
  onSetupError: (callback) => {
    ipcRenderer.on('setup-error', (_event, data) => callback(data));
  },

  // Platform info (read-only)
  platform: process.platform
});
