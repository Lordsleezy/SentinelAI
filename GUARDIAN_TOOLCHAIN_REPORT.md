# Guardian Toolchain Report
**Branch:** `fix/stability-guardian-professionalization`  
**Date:** 2026-06-02

---

## Overview

Guardian has been upgraded from a 5-stage ad-hoc scanner to a 7-stage AI orchestrator coordinating the full ProjectDiscovery + OWASP security tool stack.

---

## Tool Status

| Tool | Status | Source |
|------|--------|--------|
| **Nuclei** | ✗ Not installed | [projectdiscovery/nuclei](https://github.com/projectdiscovery/nuclei/releases) |
| **httpx** | ✓ Installed | [projectdiscovery/httpx](https://github.com/projectdiscovery/httpx/releases) |
| **Subfinder** | ✗ Not installed | [projectdiscovery/subfinder](https://github.com/projectdiscovery/subfinder/releases) |
| **Katana** | ✗ Not installed | [projectdiscovery/katana](https://github.com/projectdiscovery/katana/releases) |
| **ZAP** | ✗ Not running | [zaproxy.org](https://www.zaproxy.org) — `docker run -d -p 8090:8080 ghcr.io/zaproxy/zaproxy:stable zap.sh -daemon` |
| **Amass** | ✗ Not installed | [owasp-amass/amass](https://github.com/owasp-amass/amass/releases) |
| **ReconFTW** | ✗ Not installed | [six2dez/reconftw](https://github.com/six2dez/reconftw) |

**Note:** All missing tools are gracefully skipped. Guardian produces a final report regardless of which tools run.

---

## Assessment Workflow (7 Stages)

```
Guardian Scan — example.com
│
├── 5%   Stage 1: Target Validation
│         curl + HTTP header probe
│
├── 15%  Stage 2: Subdomain Enumeration
│         Subfinder (passive) + Amass (DNS mapping)
│         → feeds into httpx + Nuclei
│
├── 30%  Stage 3: Technology Detection
│         httpx: live hosts, status codes, tech fingerprint, TLS
│
├── 45%  Stage 4: Endpoint Discovery
│         Katana: deep crawl (depth=3), route discovery
│         → feeds into Nuclei
│
├── 55%  Stage 5: Vulnerability Scan
│         Nuclei: CVEs, vulnerabilities, exposures (critical/high/medium)
│         Findings persisted to FaradayStore (SQLite)
│
├── 65%  Stage 6: ZAP Passive Scan
│         OWASP ZAP: passive scan, alerts
│         Findings persisted to FaradayStore
│
├── 80%  Stage 7: AI Analysis
│         Ollama: synthesizes all findings into actionable intelligence
│
└── 100% Final Report
          Structured Markdown: Executive Summary, Assets, Technologies,
          Subdomains, Services, Vulnerabilities, Risk Score,
          Recommendations, Tool Status, Missing Tools
          Saved to: memory/vault/guardian_reports/<session_id>.md
```

---

## New Files

### `workers/guardian/tools/httpx_tool.py`
- Wraps ProjectDiscovery httpx
- Technology fingerprinting, status codes, TLS info, live host discovery
- Input: list of hosts/URLs; Output: structured `HttpxResult`

### `workers/guardian/tools/subfinder_tool.py`
- Wraps ProjectDiscovery Subfinder
- Passive subdomain enumeration
- Results automatically chain into httpx and Nuclei

### `workers/guardian/tools/katana_tool.py`
- Wraps ProjectDiscovery Katana
- Deep endpoint/route discovery (configurable depth)
- Discovered endpoints fed into Nuclei for targeted scanning

### `workers/guardian/tools/amass_tool.py`
- Wraps OWASP Amass
- Passive DNS/infrastructure mapping and relationship discovery
- Generates infrastructure overview

### `workers/guardian/tools/tool_registry.py`
- Central tool detector: instantiates all tools and checks availability at init
- `ToolRegistry.status_summary()` → one-line status shown in Guardian UI
- `ToolRegistry.status_block()` → multi-line block for final reports
- All checks are non-fatal — unavailable tools are never imported in the hot path

---

## Final Report Structure

Every Guardian assessment produces a structured Markdown report containing:

1. **Executive Summary** — AI-generated analysis of all findings
2. **Assets Found** — main target + all discovered subdomains
3. **Technologies Found** — fingerprinted via httpx
4. **Open Services** — from port scan (nmap/legacy)
5. **Endpoints Discovered** — via Katana crawl
6. **Potential Vulnerabilities** — grouped by severity (CRITICAL/HIGH/MEDIUM/LOW)
7. **Risk Score** — computed from finding severity weights (CRITICAL/HIGH/MEDIUM/LOW/INFORMATIONAL)
8. **Recommendations** — auto-generated + AI-refined
9. **Tool Status** — which tools ran vs were skipped
10. **Missing Tools** — with install instructions

Reports are saved to `memory/vault/guardian_reports/<session_id>.md`.

---

## Tool Installation Guide

To enable each tool, place the binary in `C:\Tools\` or anywhere in `PATH`:

```powershell
# ProjectDiscovery Stack (Windows)
# Download from https://github.com/projectdiscovery/

# httpx
Invoke-WebRequest -Uri "https://github.com/projectdiscovery/httpx/releases/latest/download/httpx_windows_amd64.zip" -OutFile httpx.zip
Expand-Archive httpx.zip -DestinationPath C:\Tools\

# subfinder
Invoke-WebRequest -Uri "https://github.com/projectdiscovery/subfinder/releases/latest/download/subfinder_windows_amd64.zip" -OutFile subfinder.zip
Expand-Archive subfinder.zip -DestinationPath C:\Tools\

# nuclei
Invoke-WebRequest -Uri "https://github.com/projectdiscovery/nuclei/releases/latest/download/nuclei_windows_amd64.zip" -OutFile nuclei.zip
Expand-Archive nuclei.zip -DestinationPath C:\Tools\
nuclei -update-templates  # download template library

# katana
Invoke-WebRequest -Uri "https://github.com/projectdiscovery/katana/releases/latest/download/katana_windows_amd64.zip" -OutFile katana.zip
Expand-Archive katana.zip -DestinationPath C:\Tools\

# OWASP ZAP (Docker recommended)
docker run -d -p 8090:8080 ghcr.io/zaproxy/zaproxy:stable zap.sh -daemon

# Amass
Invoke-WebRequest -Uri "https://github.com/owasp-amass/amass/releases/latest/download/amass_Windows_amd64.zip" -OutFile amass.zip
Expand-Archive amass.zip -DestinationPath C:\Tools\
```

---

## Known Limitations

- **ZAP** requires a running Docker daemon or ZAP install. Guardian uses passive scan only — no aggressive attacks.
- **Nuclei templates** require `nuclei -update-templates` after install. First run may be slow while templates download.
- **Subfinder** passive sources work without API keys but results improve significantly with configured API keys (`~/.config/subfinder/provider-config.yaml`).
- **Katana** depth=3 with timeout=120s may not fully crawl large sites. Configurable.
- **Amass** passive mode used. Active mode disabled to prevent unauthorized DNS brute-forcing.
- **FaradayStore** uses local SQLite (`memory/guardian_findings.db`). Full Faraday server integration is a future enhancement.
