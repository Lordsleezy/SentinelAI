# UI Simplification Report

**Date:** 2026-06-02  
**File:** `desktop-shell/orb.html`  
**Scope:** Navigation and input bar only. No backend or capability removal.

---

## Summary

Sentinel’s bottom navigation is reduced to **CHAT** and **SETTINGS (⚙)**. All former dock panels (Guardian, Earn, Memory, Tasks, Log, Market, Scalp) live under the **Settings hub** with a left nav and preserved loaders. The payment/wallet button was removed from the input row; wallet management remains under **Settings → Integrations**.

---

## Before / After (layout)

### Before — bottom dock

```
[ Input........................ ] [💳]
💬 CHAT | 🛡 GUARDIAN | 💰 EARN | 📈 MARKET | ⚡ SCALP | 📋 LOG | 🧠 MEMORY | ⚙ SETTINGS | 📋 TASKS
```

### After — bottom dock

```
[ Input........................................ ] [Send]
💬 CHAT | ⚙
```

### Before — feature access

Each subsystem had its own dock button opening a full right panel.

### After — feature access

```
⚙ SETTINGS
├── General
├── Memory      (Claude, ChatGPT, search, sync)
├── Earn        (discovery, research, evidence)
├── Guardian    (tools, findings, trusted targets — no Guardian chat)
├── Tasks       (running / done / failed / artifacts / workspace)
├── Logs        (chat, guardian, builder, earn, system filters)
├── Models      (API keys, Ollama local models)
├── Capabilities (builder status, learned capabilities)
├── Integrations (provider overview, payment methods)
└── Advanced    (Market, Scalp tabs)
```

---

## Navigation map

| Former dock item | New path | Loader (unchanged logic) |
|------------------|----------|---------------------------|
| CHAT | 💬 CHAT | Floating bubbles + `/api/chat` |
| GUARDIAN | Settings → Guardian | `loadGuardianPanel` |
| EARN | Settings → Earn | `loadEarnPanel` |
| MEMORY | Settings → Memory | `loadMemoryPanel` |
| TASKS | Settings → Tasks | `loadTasksPanel` |
| LOG | Settings → Logs | `loadLogPanel` |
| MARKET | Settings → Advanced → Market | `loadMarketPanel` |
| SCALP | Settings → Advanced → Scalp | `loadScalpPanel` |
| SETTINGS (models/keys) | Settings → Models | `loadSettingsModelsSection` |
| Payment 💳 | Settings → Integrations | `showWalletPanel()` |

**IPC / tray menus:** `open-panel` events (`earn`, `guardian`, `log`, `market`, `scalp`, etc.) still work — they route through `openPanel()` → `openSettingsHub(section)`.

**Helpers:** `openLog()` → Logs section; `openWorker(name)` maps legacy worker ids to hub sections.

---

## CHAT as primary experience

- Single input + **Send** (and Enter) posts to `/api/chat`.
- Sentinel capability router (backend) routes Guardian, Builder, Earn, memory — unchanged.
- New messages auto-show floating bubbles if the layer was hidden.
- Copy updated: errors suggest **Settings → Logs** instead of a dock LOG button.

---

## Input bar

| Removed | Kept |
|---------|------|
| 💳 payment button | Full-width input |
| Extra spacing for wallet | **Send** button |
| | Worker status line (unchanged) |

Purchases that need a card still use the purchase-approval flow; users add methods via **Integrations**.

---

## Settings hub implementation

- `loadSettingsHub()` — shell with `.settings-hub-nav` + `#settings-hub-content`
- `openSettingsSection(id)` — switch section without closing panel
- `openSettingsHub(id)` / `openPanel(name)` — open or toggle panel
- `cleanupSettingsHubSection()` — disposes log terminal / market interval when leaving a section
- `panelState.settings.section` — persisted when switching away from Settings
- Panel width: `min(560px, 44vw)` to fit nav + content

---

## Functionality preservation verification

| Area | Status | Notes |
|------|--------|-------|
| Chat / floating bubbles | ✅ | CHAT toggle unchanged |
| `/api/chat` routing | ✅ | No backend changes |
| Guardian scans | ✅ | Chat + Settings → Guardian panel |
| Earn discovery/research | ✅ | Full `loadEarnPanel` in hub |
| Memory providers/sync | ✅ | Full `loadMemoryPanel` |
| Tasks + artifacts | ✅ | Tabs + socket updates use `isSettingsSectionActive('tasks')` |
| Logs + xterm | ✅ | Section filters: Chat, Guardian, Builder, Earn, System |
| Models / API keys | ✅ | Models section |
| Builder status | ✅ | Capabilities + Tasks builder block |
| Market / Scalp | ✅ | Advanced subsection |
| Wallet / payments | ✅ | Integrations (not on input bar) |
| Orb | ✅ | Not moved or resized by this sprint |
| Earn/Memory/Guardian **backend** | ✅ | Not modified |

---

## Screenshots (capture manually)

Suggested captures when the app is running:

1. **Before** (prior build or mockup): full 9-button dock + payment icon  
2. **After — idle:** Orb + CHAT + ⚙ only  
3. **After — Settings hub:** nav visible with Tasks or Earn section open  
4. **After — input:** Input + Send, no 💳  

Save under e.g. `docs/screenshots/ui-simplification-*.png` if desired.

---

## Files touched

- `desktop-shell/orb.html` — dock, input, settings hub, routing helpers  
- `UI_SIMPLIFICATION_REPORT.md` — this document  

`desktop-shell/main.js` tray `open-panel` IPC unchanged and compatible with new routing.
