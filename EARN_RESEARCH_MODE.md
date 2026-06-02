# Earn Research Mode

Transforms Earn from program-analysis-only into a **research-assistant** pipeline: scope → controlled recon → technology mapping → research plan → potential findings → evidence vault. **No automatic bounty submission.**

## Workflow

```
Research Program (or API)
    ↓
Accept Program
    ↓
Analyze Scope (HackerOne intel)
    ↓
Launch Research Pipeline
    ├── Guardian recon (in-scope only): Subfinder → httpx → Katana → Nuclei
    ├── Technology detection
    ├── Research plan per target
    ├── Potential findings (Idea status)
    └── Evidence vault scaffolding
```

## UI (Earn panel only — not chat)

- **Discovery** tab — existing program dashboard
- **Research** tab — sessions, findings, evidence counts
- **Research Program** button — on program detail (alongside Accept & Work)

## API

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/earn/research/start` | Start pipeline (body = program JSON) |
| GET | `/api/earn/research/sessions` | List research sessions |
| GET | `/api/earn/research/<id>` | Full session payload |
| POST | `/api/earn/research/<id>/finding/<fid>/status` | Update finding status |
| POST | `/api/earn/research/<id>/evidence` | Add evidence note/log |

## Vault layout

```
memory/vault/research/
  sessions/res_<id>.json
  res_<id>/
    evidence/
    recon/          # subfinder, httpx, katana, nuclei outputs
    logs/
    screenshots/
```

## Potential Finding

| Field | Description |
|-------|-------------|
| title | Short hypothesis |
| target | In-scope URL/host |
| category | access_control, api_graphql, web, … |
| evidence | Why suggested |
| confidence | 0.0–1.0 |
| status | Idea → Investigating → Needs Validation → Validated / Rejected |

Workflow stages: `idea` → `research` → `evidence` → `validation` → `human_review`

## Guardian integration

- Uses `SubfinderTool`, `HttpxTool`, `KatanaTool`, `NucleiTool` directly
- **Does not** modify `guardian_brain` workflows
- Filters all targets to **in-scope hosts only**

## Phase 10 placeholders

`submission_draft`, `impact_analysis`, `reproduction_steps` remain `null` — human review required.

## Modules

```
workers/earn/research/
  pipeline.py          — orchestration
  scope.py             — scope analysis
  guardian_recon.py    — controlled recon
  tech_detect.py       — framework/CMS/cloud/auth/API
  research_plan.py     — suggested research per target
  findings.py          — potential findings
  store.py             — vault persistence
  models.py            — data objects
```

## Tests

```bash
python run_earn_research_tests.py
```

## Demonstration path

1. Open **EARN** → select program → **Research Program**
2. Switch to **Research** tab — watch pipeline progress
3. Review **Research Plan** (e.g. GraphQL → IDOR, introspection)
4. Review **Potential Findings** (status: Idea)
5. Evidence under `memory/vault/research/<session_id>/evidence/`

**Not modified:** Builder, Memory manager, chat UI.
