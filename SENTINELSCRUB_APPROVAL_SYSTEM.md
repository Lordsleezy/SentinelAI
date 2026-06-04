# SentinelScrub Approval System

## When approval is required

`ApprovalGate.requires_approval(action_type)` returns true for:

- purchase  
- payment  
- account_create  
- subscription  
- credential_change  
- financial  

Plan steps with `requires_approval: true` or matching `action_type` pause the goal in **`awaiting_approval`**.

## Approval record

| Field | Description |
|-------|-------------|
| `approval_id` | UUID |
| `goal_id` | Parent goal |
| `action` | Action type label |
| `cost` | Optional cost string |
| `account` | Target account |
| `expected_result` | Human-readable outcome |
| `provider_id` | Provider context |
| `status` | `pending` \| `approved` \| `rejected` |

## UI (Settings → SentinelScrub)

Pending approvals show:

- Action, cost, account, expected result  
- **Approve** / **Reject**

## API

```
GET  /api/sentinelscrub/approvals
POST /api/sentinelscrub/approvals/{id}/resolve
     { "approved": true|false, "trust_provider": false }
```

On approve → `resume_after_approval()` continues execution in background thread.

## Auto-trust

If `trust_provider` is set and provider is trusted (in-memory map), non-credential actions may skip dialog (credential changes always require approval).

## Chat integration (roadmap)

Approval cards in floating chat bubbles mirroring Settings panel.
