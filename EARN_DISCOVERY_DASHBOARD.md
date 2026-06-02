# Earn Discovery Dashboard

Browse, search, filter, and sort **500+** HackerOne bounty programs without leaving Sentinel.

## Data source

Programs come from **bounty-targets-data** (GitHub mirror of HackerOne scope). Not hardcoded.

| Endpoint | Purpose |
|----------|---------|
| `GET /api/earn/discovery/dashboard` | Full dashboard payload |
| `GET /api/earn/discovery/dashboard?refresh=1` | SCAN NOW — refetch upstream |
| `GET /api/earn/discovery/dashboard?force=1` | Force refresh — bypass cache |
| `GET /api/earn/discovery/program/<handle>` | Program detail + top 5 recommendations |
| `POST /api/earn/discovery/log` | UI events → `[EARN]` log stream |
| `GET /api/earn/diagnostics` | Cache/source diagnostics |

## UI (Earn panel in orb.html)

### Discovery overview

- Programs Available / Active Programs
- Last Refresh, Source (API / Cache), Cache Age, Discovery Duration
- Web / Mobile / API target counts
- Highest & Average bounty

### Metrics row

- Programs Discovered
- Programs Analyzed (`memory/vault/bounties/*_intel.json`)
- Reports Generated (`*.md` in bounties vault)
- Potential Reward Pool (sum of max bounties, active programs)

### Program table (virtualized)

Columns: Program, Platform, Bounty, Assets, Web, Mobile, API, Last Updated, Source.

- **Virtual scrolling** — only visible rows rendered (~36px row height)
- Handles 500+ programs without UI freeze

### Search

Live filter on: program name, handle, domains, scope assets, bounty text.

### Filters

- All, Web, Mobile, API, High Bounty (≥$2.5k max), Low Scope (≤10 assets), Large Scope (≥30 assets)
- Platform: All, HackerOne, Bugcrowd, Intigriti

### Sort

Highest/Lowest Bounty, Most/Least Assets, Newest/Oldest, Alphabetical

### Program details (right panel)

Click a row: description, scope summary, in/out counts, mobile targets, domains, top 5 recommendations (analyzer), **Accept & Work**.

## Logging (`[EARN]`)

- Dashboard Loaded
- Discovery Started / Force refresh
- Source API · Programs Discovered · Duration
- Search Query
- Filter Applied
- Sort Applied
- Program Selected

## Modules

```
workers/earn/dashboard_enrich.py   — per-program dashboard fields
workers/earn/dashboard_service.py  — aggregate load, detail, metrics
workers/earn/program_discovery.py  — upstream + disk cache (unchanged contract)
```

## Tests

```bash
python run_earn_dashboard_tests.py
```

**Latest run:** all checks passed (enrich, load 230+ programs, filters, program detail + recommendations).

## Screenshots

Captured previews (restart `desktop_app.py` to load live dashboard API routes if `/api/earn/discovery/dashboard` returns 404 on an old process):

| File | Description |
|------|-------------|
| `docs/screenshots/earn_dashboard/01_overview_table.png` | Overview cards, metrics, virtualized table sample |
| `docs/screenshots/earn_dashboard/02_search_filtered.png` | Search filter (`twilio`) |
| `docs/screenshots/earn_dashboard/dashboard_snapshot.json` | Overview + metrics snapshot |

Regenerate:

```bash
python scripts/capture_earn_dashboard_screenshots.py
```

Live UI: start backend, open orb, click **EARN** — SCAN NOW / FORCE REFRESH, search, filters, row click for detail + top 5 recommendations.

## Out of scope (per request)

- Guardian, Builder, Memory modules were **not** modified.
