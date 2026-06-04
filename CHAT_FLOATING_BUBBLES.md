# Chat Floating Bubbles — Implementation

**Date:** 2026-06-02  
**Scope:** Chat UI only (`desktop-shell/orb.html`). Orb, dock, panels, and send pipeline unchanged in behavior.

---

## Before

```
┌─────────────────────────────────────────────────────────────┐
│ CHAT click → left sidebar (380px) opens                     │
│ ┌──────────────┬──────────────────────────┬──────────────┐  │
│ │ Chat panel   │         ORB (shrinks)    │ Right panel  │  │
│ │ (sidebar)    │                          │ (optional)   │  │
│ │ messages     │                          │              │  │
│ └──────────────┴──────────────────────────┴──────────────┘  │
│ [ input ]  [ 💬 CHAT ] [ GUARDIAN ] …                       │
└─────────────────────────────────────────────────────────────┘
```

- `#left-panel-container` slid open from the left.
- Orb width reduced; `resize` fired after toggle.
- Messages in `#chat-history` with flat bordered boxes.
- Transient replies also used `#response-area` overlay.

---

## After

```
┌─────────────────────────────────────────────────────────────┐
│ CHAT click → floating bubbles ON/OFF (no layout shift)      │
│ ┌────────────────────────────────────────────────────────┐  │
│ │              ORB (full width, always centered)        │  │
│ │    ┌─────────────────────────┐                        │  │
│ │    │ Sentinel bubble (left)  │  ← transparent overlay │  │
│ │              ┌──────────────────┐                       │  │
│ │              │ User bubble (right)│                      │  │
│ │    └─────────────────────────┘                        │  │
│ └────────────────────────────────────────────────────────┘  │
│ [ input ]  [ 💬 CHAT ● ] [ GUARDIAN ] …                     │
└─────────────────────────────────────────────────────────────┘
```

- `#floating-conversation-layer` over `#orb-container` (`z-index: 12`).
- Background **transparent** — Orb always visible.
- CHAT toggles `.visible` on the layer (show/hide only; history kept in DOM).
- iMessage-style bubbles: user right / blue, Sentinel left / dark gray, 18px radius.

---

## Components

| ID / object | Role |
|-------------|------|
| `#floating-conversation-layer` | `FloatingConversationLayer` root overlay |
| `#floating-conversation-messages` | Scrollable message stack |
| `FloatingConversationLayer` (JS) | `toggle()`, `setVisible()`, `scrollToEnd()` |
| `toggleChatPanel()` | Same dock handler; toggles bubbles |
| `renderChatMsg()` | Renders `.chat-bubble-row` + `.chat-bubble` |
| `appendChatPanelMessage()` | Session store + render + API persist |
| `showChatResponse()` | Routes to `appendChatPanelMessage('sentinel', …)` |
| `_appendChatMsg()` | Alias for tasks/artifacts notifications |

---

## Removed / disabled

- Left chat sidebar: `#left-panel-container { display: none !important; }`
- `#response-area` flash overlay: disabled (`display: none`); chat, plan, and purchase feedback use `showChatResponse()` → bubbles
- Layout `resize` on chat toggle: removed (Orb size unchanged)

---

## Preserved

- Bottom `#chat-input` and Enter → `/api/chat`
- `chatPanelMessages[]` session history
- `loadChatHistory()` from `/api/memory/recent`
- `appendChatPanelMessage` → `/api/memory/session`
- Socket: `forge_complete`, Guardian `showChatResponse`, earn updates via same helpers
- CHAT dock button: `toggleChatPanel()` + `.active` state

---

## Animations

- New messages: `chat-bubble-in` (fade + 8px slide up, 280ms)
- Layer show/hide: opacity + visibility 250ms
- Auto-scroll: `scrollToEnd()` on new message when visible

---

## Screenshots (capture manually)

1. **Before (git prior commit):** CHAT open with left sidebar — if unavailable, use description above.
2. **After — hidden:** Orb only, CHAT button inactive.
3. **After — visible:** Bubbles over Orb after sending “Build Flappy Bird” and receiving Sentinel replies.
4. **After — toggle off:** Same messages reappear when CHAT clicked again.

Suggested paths when capturing:

- `docs/screenshots/chat-before-sidebar.png`
- `docs/screenshots/chat-after-bubbles-visible.png`
- `docs/screenshots/chat-after-bubbles-hidden.png`

---

## Verification checklist

- [ ] CHAT toggles bubbles without moving Orb
- [ ] No left panel appears
- [ ] History survives hide/show
- [ ] User bubbles right-aligned, Sentinel left-aligned
- [ ] `forge_complete` and launch button still attach to last Sentinel bubble
- [ ] Guardian/security messages appear when `showChatResponse` is called
