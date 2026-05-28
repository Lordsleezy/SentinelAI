'use strict';

const { contextBridge, ipcRenderer } = require('electron');

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

  // Platform info (read-only)
  platform: process.platform
});
