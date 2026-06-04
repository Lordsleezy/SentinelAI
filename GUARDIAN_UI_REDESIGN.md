# Guardian UI Redesign

## Objective

Guardian remains a **first-class engine** but must not feel like a **separate AI product**.

| Move toward | Move away from |
|-------------|----------------|
| Modern, minimal, professional | Neon / terminal aesthetic |
| Sentinel capability tone | “Guardian bot” identity |
| Shared design tokens with orb shell | Isolated cyberpunk panel |

**Constraint:** Do **not** modify the **Orb** visual or animation.

---

## Current UI Surfaces (audit)

| Surface | File | Notes |
|---------|------|-------|
| Inline Guardian panel | `desktop-shell/orb.html` | Separate `#guardian-chat-messages`, settings drawer, tool status |
| Standalone window | `desktop-shell/guardian_window.html` | Richer tabs, marked.js |
| Main chat | `#chat-input` → `/api/chat` | Unified Sentinel (target) |

**Backend:** `/guardian/chat` for panel; unified routing should also invoke `GuardianBrain` from `/api/chat` for scan intents.

---

## Design Tokens (target — align with platform UI)

```css
/* Reference tokens for Guardian panel refresh */
--sentinel-bg: #0a0a0b;        /* near black */
--sentinel-panel: #141416;     /* dark gray */
--sentinel-border: #2a2a2e;    /* minimal border */
--sentinel-text: #f5f5f7;
--sentinel-text-muted: #8e8e93;
--sentinel-accent: #5e9eff;    /* subdued blue, not neon cyan */
--sentinel-success: #34c759;
--sentinel-warning: #ff9f0a;
--sentinel-danger: #ff453a;
```

**Typography:** System UI stack or existing orb font — no monospace “hacker” default for body text.

**Spacing:** 8px grid, 12–16px panel padding, 4px borders max.

---

## Information Architecture

1. **Chat** — Same conversational patterns as main Sentinel (user can use main chat for scans).
2. **Findings** — Structured results (see `FINDINGS_CENTER_ARCHITECTURE.md`).
3. **Settings** — Mode, trusted targets, bootstrap, model — drawer (already started).
4. **Tools** — Status list (installed / version / health) — reuse capability registry rows.

Remove duplicate “AI name” headers; label section **Security** or **Guardian** as a *mode*, not a persona.

---

## Interaction Model

| User says (main chat) | Sentinel responds | Internal |
|-----------------------|-------------------|----------|
| scan example.com | “Starting security assessment…” | `guardian` engine |
| show findings | Summary + link to panel | findings center API |

Guardian panel remains for power users (mode toggle, tool run, findings drill-down).

---

## Implementation Phases

| Phase | Work | Risk |
|-------|------|------|
| 1 | CSS token pass on `#guardian-*` in orb.html | Low |
| 2 | Unified chat routing (backend) | Low |
| 3 | Findings table UI | Medium |
| 4 | Deprecate duplicate styling in guardian_window.html | Low |

**Do not remove** offensive-lab ack, trusted targets, or bootstrap controls.

---

## Inspiration Reference

Layout density similar to Cursor / Linear / Claude settings panels: quiet headers, clear hierarchy, no glow effects.
