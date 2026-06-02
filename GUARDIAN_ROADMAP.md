# Guardian Expansion Roadmap

Modular **security assessment and threat intelligence** platform. Defensive research, visibility, and reporting only — no offensive exploitation modules.

**Out of scope for this roadmap doc:** Earn, Builder, Memory.

---

## Phase 1 — Recon Core

| Tool | Purpose | Status |
|------|---------|--------|
| Subfinder | Subdomain discovery | ✓ Core pipeline |
| **Naabu** | Port discovery | Roadmap — bundle target |
| httpx | HTTP probe / tech | ✓ Core pipeline |
| Katana | Crawl / endpoints | ✓ Core pipeline |
| Nuclei | Template scanning | ✓ Core pipeline |

**Workflow:** Subfinder → Naabu → httpx → Katana → Nuclei

---

## Phase 2 — Advanced Enumeration

| Tool | Purpose |
|------|---------|
| Amass | Deep subdomain enum |
| Assetfinder | Passive recon |
| dnsx | DNS resolution / validation |

**Workflow:** Subfinder → Assetfinder → Amass → dnsx → Naabu → httpx

---

## Phase 3 — Web Security

| Tool | Purpose |
|------|---------|
| OWASP ZAP | Passive web analysis |
| ffuf | Content discovery |

**Workflow:** Katana → ffuf → ZAP → Nuclei

---

## Phase 4 — Screenshot & Visual Review

| Tool | Purpose |
|------|---------|
| gowitness | Screenshot discovered hosts |

**Outputs:** Gallery, login pages, admin panels → embedded in Guardian reports.

---

## Phase 5 — Threat Intelligence

Integrations (public APIs only):

- AbuseIPDB
- AlienVault OTX
- URLHaus
- PhishTank

**Capabilities:** IP/domain reputation, malware & phishing indicators.

---

## Phase 6 — Crypto Threat Intelligence

**Module:** `CRYPTO INTEL`

| Command | Action |
|---------|--------|
| `guardian investigate wallet <address>` | Scam/phishing/sanctions checks |
| `guardian investigate tx <hash>` | Transaction summary |
| `guardian investigate domain <domain>` | ENS / domain intel |

**Output:** Risk score, associations, threat summary (public sources only).

---

## Phase 7 — Reporting

**Sections:** Executive summary, attack surface, infrastructure map, assets, endpoints, screenshots, threat intel, findings, recommendations, risk score.

**Export:** PDF, Markdown, JSON.

---

## Phase 8 — Sentinel Vision Integration

**Guardian Vision Mode** — analyze screenshots / web UIs for headers, sensitive exposure, misconfigurations, high-value targets.

---

## Tool Status Panel

Guardian orb panel → **TOOL STATUS**

- **Active pipeline:** httpx, Subfinder, Katana, Nuclei, Amass, ZAP, …
- **Roadmap modules:** Naabu, Assetfinder, dnsx, ffuf, gowitness, Threat Intel, Crypto Intel

Each row: **✓ Bundled** | **✓ System** | **✗ Missing** | **Phase N — planned**

API: `GET /api/guardian/tools/status`

---

## Implementation notes

1. New tools ship as `workers/guardian/tools/<tool>_tool.py` + registry entry.
2. Stages plug into `guardian_brain._run_full_assessment()` with skip-on-missing semantics (same as httpx/Katana today).
3. Bundled binaries use `workers/guardian/bundled_toolchain.py` + `guardian_tool_fetcher.py`.
4. All stage logs use `[GUARDIAN]` prefix.

See also: `GUARDIAN_HTTPX_PARSER_FIX.md` for httpx stdout parsing.
