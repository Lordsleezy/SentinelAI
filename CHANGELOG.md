# Changelog

All notable changes to Sentinel AI are documented here.

## [1.0.0-beta.1] — 2026-06-02

### Added
- **Sentinel Vision** — merged operator subsystem (browser, desktop, provider onboarding, workflow library, OCR/vision fallback)
- **Memory 2.0** — unified long-term, project, workflow, repair, and preference memory (`core/memory2`)
- **Mission System** — persistent missions with Vision goal attachment (`core/missions`)
- **Guardian foundation** — real psutil system monitor, dashboard API, alerts with remediation
- **Auto-updater** — GitHub Releases, beta/stable channels, background download, SHA-256 verify, rollback metadata
- **Release manager** — version API, manifest, build verification, changelog endpoint
- **Dependency manager** — scan/install/repair runtime components (`core/dependency_manager`)
- **Model manager** — hardware-based Llama + Dolphin recommendations only (`core/model_manager`)
- **First launch orchestrator** — API-driven onboarding steps (`core/onboarding`)
- Settings hub: Downloads, Updates, Missions, Sentinel Vision
- Website beta release API and admin endpoints (token-protected)

### Changed
- SentinelScrub APIs alias to Sentinel Vision (`/api/sentinelvision/*`)
- Vault prefix `vision:vault:` with legacy `scrub:vault:` read support
- Default beta version `1.0.0-beta.1`; `generate_build_info.ps1` supports `beta` build type

### Security
- License restricted mode on beta expiry (non-destructive, no file deletion)
- Remote feature disable and offline policy cache

### Known limitations
- Website uses SQLite activation codes, not Supabase auth
- Stripe on website is one-time PaymentIntent; subscription tiers require Stripe Checkout extension
- Ollama install requires user-run installer on Windows
- `SentinelAISetup.exe` must be produced by installer pipeline before beta portal links live build
