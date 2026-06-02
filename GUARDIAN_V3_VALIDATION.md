# Guardian v3 Validation Report

**Generated:** 2026-06-02T14:54:15.839093

## Installed Tools

| Tool | Status | Version | Health | Path |
|------|--------|---------|--------|------|
| ProjectDiscovery httpx | ✓ Bundled | v1.9.0 | ok | `C:\Users\pgg12\Desktop\SentinelAI\tools\httpx\httpx.exe` |
| Subfinder | ✓ Bundled | v2.14.0 | ok | `C:\Users\pgg12\Desktop\SentinelAI\tools\subfinder\subfinder.` |
| Katana | ✓ Bundled | v1.6.1 | ok | `C:\Users\pgg12\Desktop\SentinelAI\tools\katana\katana.exe` |
| Nuclei | ✓ Bundled | v3.8.0 | ok | `C:\Users\pgg12\Desktop\SentinelAI\tools\nuclei\nuclei.exe` |
| Naabu | ✗ Missing | — | missing | `` |
| dnsx | ✗ Missing | — | missing | `` |
| ffuf | ✗ Missing | — | missing | `` |
| assetfinder | ✗ Missing | — | missing | `` |
| Amass | ✗ Missing | — | — | `` |
| ZAP | ✗ Missing | — | — | `` |
| gowitness | ✗ Missing | — | — | `` |
| Threat Intel (OTX / AbuseIPDB / KEV) | ✓ Module | v3 | ok | `workers/guardian/guardian_threat_intel.py` |

## Missing Tools

naabu, dnsx, ffuf, assetfinder, amass, zap, gowitness, reconftw, crypto_intel

## Tool Versions (core)

- **httpx**: v1.9.0 (✓ Bundled)
- **subfinder**: v2.14.0 (✓ Bundled)
- **katana**: v1.6.1 (✓ Bundled)
- **nuclei**: v3.8.0 (✓ Bundled)
- **naabu**: unknown (✗ Missing)
- **dnsx**: unknown (✗ Missing)
- **ffuf**: unknown (✗ Missing)
- **assetfinder**: unknown (✗ Missing)

## AI Runtime Status

- **Selected model:** `qwen2.5-coder:14b`
- **Status:** idle
- **Ollama URL:** http://localhost:11434
- **Installed models:** 5
- **VRAM (MB):** 1283
- **Last inference (ms):** None

## Pipeline Status

- GuardianBrain loads: **OK**
- Stage logging: Entering / Running / Completed / Skipped / Failed
- Extended stages: assetfinder, dnsx, naabu, ffuf, threat intel

## Task System Status

- create/update/get: **OK** (`task_64d6b5b2aa`)

## Threat Intel Status

- Module loads: **OK**
- Sources used: ['alienvault_otx', 'cisa_kev', 'openphish']
- Summaries: 3
- Notes: Set OTX_API_KEY and/or ABUSEIPDB_API_KEY for full domain/IP reputation.

## Findings DB

- SQLite store: **OK** (rows=2, last_id=2)

## Trusted Targets

- sentinelprime.org trusted: **True**
- Count: 1

## Performance Metrics

- Tool probe batch: 260 ms

## Remaining Gaps

- Install missing pipeline tools: naabu, dnsx, ffuf, assetfinder, amass, zap, gowitness, reconftw, crypto_intel
- Auto-update of tool binaries (version pin / refresh policy)
- gowitness screenshot pipeline stage
- Full AbuseIPDB/OTX without API keys (limited public data only)
- Crypto threat intel execution (roadmap module only)
- Unify guardian_worker file-scan API with GuardianBrain pipeline branding
- GPU metrics when nvidia-smi unavailable

## Validation Result

**PASSED** — core v3 modules operational.