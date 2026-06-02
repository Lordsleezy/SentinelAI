# Guardian Findings Center

Module: `workers/guardian/findings_center.py`  
Storage: `memory/vault/findings/<session_id>/`

## Structure per session

| Bucket | Content |
|--------|---------|
| hosts | Live URLs / subdomains |
| ports | Port scan lines |
| technologies | httpx tech tags |
| endpoints | Katana crawl URLs |
| screenshots | Reserved for gowitness |
| findings | Structured finding records |

## Finding record

- title
- severity: informational | low | medium | high | critical
- confidence
- evidence
- tool_source
- discovery_path
- ai_explanation
- created_at

Files: `findings/find_<id>.json` + `meta.json`

## API

`GET /api/guardian/findings/center`  
`GET /api/guardian/findings/center?session_id=<id>`

## Population

Automatically during Guardian scan pipeline (subdomains, httpx, katana, nuclei).

## UI

Settings → Findings Center shows latest session summary.
