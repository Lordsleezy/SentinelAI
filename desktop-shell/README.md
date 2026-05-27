# SentinelAI Desktop Shell

Minimal Electron shell foundation for SentinelAI desktop application.

## Overview

This is a **minimal foundation** for the SentinelAI desktop application. It provides:

- ⚡ Electron-based desktop shell
- 🎨 Futuristic dark UI placeholder
- 🔒 Secure context isolation
- 🚀 Ready for backend integration

## Current Status

**Phase: Foundation Only**

This shell currently displays a placeholder "Initializing..." screen. It does NOT yet:

- Launch the Python backend
- Connect to SentinelAI services
- Provide dashboard functionality
- Include module navigation

## Structure

```
desktop-shell/
├── main.js          # Electron main process
├── preload.js       # Secure IPC bridge
├── index.html       # Minimal UI placeholder
├── package.json     # Dependencies & scripts
└── README.md        # This file
```

## Installation

```bash
npm install
```

## Running

```bash
npm start
```

This will open the Electron window with the placeholder UI.

## Next Steps

Future development will add:

1. Python backend launcher
2. Health monitoring
3. Dashboard integration
4. Module navigation
5. IPC communication
6. Process management

## Development Notes

- Uses Electron v23
- Context isolation enabled
- Node integration disabled
- Secure preload bridge configured

---

**Part of the SentinelAI ecosystem**
