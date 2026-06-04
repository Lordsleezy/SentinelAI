# Autonomy Score (Phase 2J)

**Module:** `core/sentinelscrub/metrics/autonomy_score.py`  
**Database:** `data/sentinelscrub/autonomy_metrics.db`  
**API:** `GET /api/sentinelscrub/metrics`  
**UI:** Settings → SentinelScrub (score card)

## Metrics recorded

| Phase | When recorded |
|-------|----------------|
| research | After research completes |
| plan | After plan built |
| execute | After execution phase |
| verify | After autonomous verification |
| repair | After self-correction cycle |
| complete | Goal completed or failed |

## Displayed percentages

- Research Success %  
- Plan Success % (via plan phase)  
- Execute Success %  
- Verification Success %  
- Repair Success %  
- Task Completion % (`complete` phase)  
- Provider Success % (execute bucket)  

## Autonomy Score formula

Weighted composite (target **95%+**):

| Phase | Weight |
|-------|--------|
| research | 15% |
| plan | 10% |
| execute | 30% |
| verify | 25% |
| repair | 10% |
| complete | 10% |

## Usage

Score increases as goals complete without manual repair.  
Failed goals record `complete: false` — pulls score down until repair memory and playbooks improve outcomes.

## Goal

**95%+ successful autonomous completion** across real provider workflows with credentials in vault and Playwright/Ollama available.
