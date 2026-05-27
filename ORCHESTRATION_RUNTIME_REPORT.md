# SentinelAI Orchestration Runtime Report

## What Changed

SentinelAI now has an additive persistent orchestration layer for AI worker workflows.

Added core packages:

- `orchestration/`
- `workflows/`
- `graph_runtime/`
- `checkpoint_system/`

The new layer provides:

- Persistent workflow records in SQLite
- Workflow checkpoints
- Approval checkpoints
- Recovery of interrupted workflows
- Retry state tracking
- Agent memory
- Execution logs
- LangGraph-compatible graph execution
- CrewAI-compatible worker agent definitions

## Runtime Model

The orchestration runtime is intentionally additive. It does not replace:

- existing queue manager
- worker manager
- watchdog
- health monitor
- learning memory
- approval gates
- dry-run protections
- rollback protections
- emergency controls

`desktop_app.py` initializes the orchestration runtime after the queue comes online and registers an `orchestration_workflow` handler with the existing worker manager.

## Worker Agents

Initial worker agents:

- ResearchAgent
- CodingAgent
- DebuggingAgent
- UIAgent
- MonitoringAgent
- DeploymentAgent
- RevenueDiscoveryAgent

Each agent can operate through CrewAI when installed. A local Sentinel fallback remains available so the runtime can still validate and persist state before dependencies are installed.

## LangGraph Integration

`graph_runtime/langgraph_adapter.py` is the primary workflow graph adapter. When LangGraph is installed, it compiles the workflow through `StateGraph`. When unavailable, it uses the same node contract through a deterministic fallback so the rest of SentinelAI remains stable.

Workflow nodes:

- `route_task`
- `approval_checkpoint`
- `execute_agent`
- `persist_result`

## Persistence

SQLite tables added:

- `orchestration_workflows`
- `workflow_checkpoints`
- `orchestration_execution_logs`
- `orchestration_agent_memory`
- `orchestration_approvals`

These tables are created without altering existing tables.

## API Endpoints

Added:

- `GET /api/orchestration/status`
- `GET /api/orchestration/workflows`
- `GET /api/orchestration/workflows/<id>`
- `POST /api/orchestration/workflows`
- `POST /api/orchestration/workflows/<id>/run`
- `GET /api/orchestration/approvals`
- `POST /api/orchestration/workflows/<id>/approve`
- `POST /api/orchestration/workflows/<id>/reject`

Mutating endpoints require the existing SentinelAI auth token.

## Validation

Added `test_orchestration_runtime.py` to validate:

- runtime initialization
- agent registry
- workflow completion
- approval pause/resume behavior
- queue handler integration
- recovery of interrupted workflows
- checkpoint persistence

## Dependency Notes

`requirements.txt` now includes:

- `langgraph>=0.2.60`
- `crewai>=0.86.0`

The code remains import-safe if those packages are not installed yet.
