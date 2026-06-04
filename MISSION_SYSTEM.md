# Mission System

**Module:** `core/missions/mission_engine.py`  
**Database:** `data/missions/missions.db`  
**API:** `/api/missions`, `/api/missions/<id>`

## Mission model

| Field | Description |
|-------|-------------|
| `goal` | Primary objective |
| `progress` | 0–100 |
| `current_task` | Active step description |
| `blockers` | JSON list of impediments |
| `dependencies` | JSON list of prerequisite missions |
| `completion_state` | `not_started`, `in_progress`, `completed` |

## Templates

Built-in resolution for: Launch Sentinel AI, Configure Stripe, Connect Supabase, Deploy Website.

## Vision integration

When `SentinelVisionEngine.submit_goal()` runs:

1. `resolve_or_create(objective)` finds or creates a mission
2. `attach_vision_goal(mission_id, goal_id, objective)` links the task
3. On completion/failure, `on_vision_goal_completed()` updates progress and blockers

## UI

Settings → **Missions** lists active missions and progress.

## Persistence

SQLite survives restarts; missions are not deleted on upgrade.
