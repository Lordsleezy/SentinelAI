# Sentinel AI — Beta Tester Guide

**Version:** 1.0.0-beta.1  
**Channel:** beta

## Before you start

1. Windows 10/11 x64, 16+ GB RAM, 20+ GB free disk.
2. Install [Ollama](https://ollama.com/download) when the setup wizard prompts you (Windows installer).
3. Stable internet for license check and updates.

## Install

1. Go to [https://sentinelprime.org/download.html](https://sentinelprime.org/download.html).
2. Download the beta installer (`SentinelAISetup.exe` when published) or latest GitHub Release asset.
3. Run installer → launch Sentinel AI.
4. Complete the **Setup Wizard** (system scan, dependencies, models).
5. Optional: **Settings → Downloads** to verify Playwright, Guardian tools, Vision stack.

## Activate Pro (if purchased)

1. Purchase on pricing/checkout page.
2. Receive activation email with code.
3. Setup wizard **License** step, or **Settings** license field / `/license/activate` API.
4. Restart is not required; restricted mode clears on valid Pro.

## Updates

**Settings → Updates**

- Channel: **beta** (default for beta builds)
- **Check** — queries GitHub Releases
- **Download** — background download with checksum verify
- Restart app when prompted to apply installer

## What to test

| Area | How |
|------|-----|
| Vision | Settings → Sentinel Vision → “Connect Supabase” or “Set up Stripe” |
| Missions | Settings → Missions — progress after Vision goals |
| Guardian | Settings → Guardian → System Health panel |
| Memory | Runs automatically; API `/api/memory2/health` |
| Chat | Primary orb — routing to workers |

## Report issues

Include:

- Build version (`Settings → Updates` or `/api/version`)
- Steps to reproduce
- Logs from Settings → Logs
- Screenshot of Guardian System Health if relevant

Do **not** share activation codes or API keys.

## Restricted mode

If beta period expires without a license, Sentinel enters **restricted mode**: activate license only; **your files are not deleted**.

## Uninstall

Use Windows Add/Remove Programs. User data remains under `%USERPROFILE%\.sentinelai` and project `data/` unless you remove them manually.
