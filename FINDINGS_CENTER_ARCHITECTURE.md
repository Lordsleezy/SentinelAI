# Findings Center Architecture

## Problem

Guardian **logs** are necessary but insufficient. Operators need structured **findings** with evidence, severity, and provenance — without removing log streams.

---

## Current Implementation (audit)

### Store A — Session vault (primary for UI preview)

**Module:** `workers/guardian/findings_center.py`  
**Path:** `memory/vault/findings/<session_id>.json` + `sessions_index.json`

**Entities recorded:**

| Type | Fields |
|------|--------|
| Hosts | hostname, ip, ports |
| Domains / subdomains | name, source |
| Technologies | name, version, category |
| Endpoints | url, method, status |
| Findings | title, severity, confidence, evidence, source_tool, explanation |
| Screenshots | path references (when captured) |

**Writers:** `GuardianBrain` during assessments (`start_session`, `add_*`, `add_finding`).

**Readers:** `GET /api/guardian/findings/center`, orb Guardian settings preview.

### Store B — SQLite v3

**Module:** `workers/guardian/guardian_findings_db.py`  
**DB:** `memory/guardian_findings_v3.db`  
**API:** `/api/guardian/findings` (search/list)

**Risk:** Dual-write during scans; UI preview uses A while search API uses B.

### Earn research vault (separate)

**Path:** `memory/vault/research/` — bounty research findings, not merged with Guardian center.

---

## Target Data Model (unified read model)

```json
{
  "finding_id": "uuid",
  "session_id": "uuid",
  "target": "example.com",
  "asset_type": "subdomain|endpoint|host",
  "asset_value": "api.example.com",
  "severity": "critical|high|medium|low|info",
  "confidence": 0.0,
  "title": "SQL injection signal",
  "explanation": "Human-readable",
  "evidence": ["nuclei-output.txt", "screenshot.png"],
  "discovery_source": "nuclei",
  "discovered_at": "ISO8601",
  "status": "new|triaged|confirmed|false_positive"
}
```

---

## Architecture Diagram

```mermaid
flowchart LR
  Brain[GuardianBrain] --> FC[findings_center JSON]
  Brain --> DB[findings_db SQLite]
  FC --> API1[/api/guardian/findings/center]
  DB --> API2[/api/guardian/findings]
  API1 --> UI[Orb Guardian panel]
  API2 --> UI
  Logs[Log tab / socket] --> UI
```

**Do not remove logs.** Logs = real-time; Findings = structured post-scan asset.

---

## Extension Plan (no rebuild)

1. **Single writer helper** `record_finding(session, finding)` → writes FC + mirrors row to SQLite.
2. **Merge API** — `GET /api/guardian/findings/center` returns session meta + DB search in one payload.
3. **Screenshots** — gowitness / Playwright hooks → `evidence[]` paths in vault.
4. **Export** — Markdown report from session JSON (already partially in brain report flow).
5. **Earn bridge** — validated research finding → `add_finding` with `discovery_source=earn_research`.

---

## UI Direction

- Findings tab/section inside Guardian panel (not a separate AI).
- Table: Severity | Asset | Source | Confidence | Evidence link.
- Neutral palette per `GUARDIAN_UI_REDESIGN.md`.

---

## Logs vs Findings

| Logs | Findings |
|------|----------|
| Stream, verbose | Structured, deduplicated |
| Developer/debug | Operator/reporting |
| Always on | Per session |
| LOG tab filter | Guardian panel + API |
