# Sentinel Security Architecture

Enterprise-grade security layers implemented in `sentinel_security/` — **backend only**. No UI, UX, or workflow changes to Guardian, Earn, or Forge.

## Principles

- **Local-first** by default (`SENTINEL_CLOUD_SYNC` off)
- **Zero-trust** per module — permissions not inherited
- **Defense in depth** — audit log, signing, AI safety, self-protection

## Layers

| Layer | Module | Description |
|-------|--------|-------------|
| 1 | `local_first.py` | Audits Guardian/Earn/Forge/Vision/Memory for silent uploads |
| 2 | `zero_trust.py` | Policy: filesystem, network, browser, email, ssh, credentials |
| 3 | `secrets_store.py` | DPAPI (Windows) / user-secret PBKDF2 — no plaintext secrets |
| 4 | `vault_crypto.py` | AES-256-GCM for vault paths (`SENTINEL_VAULT_ENCRYPT=1`) |
| 5 | `pqc.py` | Kyber/Dilithium via liboqs/pqcrypto when installed; hybrid mode |
| 6 | `guardian_internal_audit.py` | Host health: ports, startup, plugins, integrity |
| 7 | `module_signing.py` | SHA-256 manifest for Guardian/Earn/Forge/Vision/Shield |
| 8 | `ai_safety.py` | Injection, exfil, credential access, tool abuse |
| 9 | `audit_log.py` | Append-only hash-chained `memory/vault/security/audit.jsonl` |
| 10 | `self_protection.py` | Critical file + module tamper detection |

## Orchestration

`sentinel_security/orchestrator.py` — `get_security().bootstrap()` on app startup.

## API (no UI)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/security/health` | Security Health report markdown + findings |
| `GET /api/security/audit` | Full audit JSON |
| `GET /api/security/audit-log` | Search audit log (`event_type`, `module`, `limit`) |

## Gates (API only)

- `POST /guardian/chat` — zero-trust + AI safety on message text
- `POST /guardian/tool/run` — tool abuse checks + audit record

Blocked requests return HTTP 403 JSON (`status: blocked`) — existing UI shows error text only.

## Configuration

| Variable | Default | Effect |
|----------|---------|--------|
| `SENTINEL_CLOUD_SYNC` | `false` | Allow cloud upload code paths |
| `SENTINEL_VAULT_ENCRYPT` | `false` | Encrypt vault files at rest |
| `SENTINEL_VAULT_KEY` | — | Base64 vault key (optional) |
| `SENTINEL_USER_SECRET` | — | PBKDF2 secrets when DPAPI unavailable |
| `SENTINEL_PQC_HYBRID` | `false` | Enable Kyber hybrid when lib present |
| `SENTINEL_SECURITY_STRICT` | `true` | Block high-risk AI/tool patterns |

## Data locations

```
memory/vault/security/
  module_policy.json
  module_manifest.json
  audit.jsonl
  secrets.enc.json
  integrity_baseline.json
```

## Validation

```bash
pip install cryptography>=42.0.0
python run_security_audit.py
python run_security_audit.py --rebuild-baseline
```

See `THREAT_MODEL.md`, `SECURITY_HEALTH_REPORT.md`.
