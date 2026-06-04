# Sentinel AI 1.0.0-beta.1 — Release Notes

**Release date:** June 2, 2026  
**Channel:** beta  
**Build:** `1.0.0-beta.1`

## Overview

First closed beta of Sentinel AI as a shippable desktop product: local-first assistant with Vision automation, Guardian security monitoring, unified memory, missions, and automatic updates.

## Highlights

### Sentinel Vision
Autonomous research → plan → execute → verify → repair for provider setup (Supabase, Stripe, Netlify, GitHub, Cloudflare, and more).

### Memory 2.0
Persistent memory across restarts with retrieval, summarization, consolidation, and health metrics.

### Missions
Long-running goals (e.g. “Launch Sentinel AI”, “Connect Supabase”) with progress, blockers, and automatic Vision task linking.

### Guardian
Real CPU, RAM, disk, network, process, and service monitoring — no synthetic telemetry.

### Auto-update
Beta testers on the **beta** channel receive GitHub Release notifications and verified background downloads.

## System requirements

- Windows 10/11 x64
- 16 GB RAM minimum (32 GB recommended)
- 20 GB free disk
- NVIDIA GPU with 8 GB VRAM recommended (CPU-only supported, slower)
- Internet for license validation, updates, and optional cloud tools

## Install

1. Download `SentinelAISetup.exe` from [SentinelPrime.org/download](https://sentinelprime.org/download.html) or GitHub Releases.
2. Run the installer (includes Python venv bootstrap).
3. Complete the first-launch wizard (dependencies + recommended models).
4. Enter Pro activation code if purchased.

## Upgrade from earlier dev builds

- Data under `data/sentinelvision/` and `data/memory2/` is preserved.
- Legacy `/api/sentinelscrub/*` routes remain aliases.

## Known issues

See `RELEASE_CANDIDATE_REPORT.md` for the full risk list.

## Support

- Email: paul@sentinelprime.org
- Docs: repository `README_BUILD.md`, `BETA_TESTER_GUIDE.md`
