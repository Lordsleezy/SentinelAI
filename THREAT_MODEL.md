# Sentinel Threat Model

## Assets

| Asset | Location | Sensitivity |
|-------|----------|-------------|
| Memory / vault | `memory/`, `memory/vault/` | High — bounties, tasks, conversations |
| Credentials | `sentinel_security/secrets.enc.json` | Critical |
| Scan artifacts | Guardian/Earn outputs | High |
| API keys | Secrets store | Critical |
| Module code | `workers/`, `builders/` | Integrity-critical |

## Trust boundaries

```
┌─────────────────────────────────────────┐
│  User workstation (trusted operator)     │
│  ┌─────────┐ ┌──────┐ ┌───────┐ ┌─────┐ │
│  │ Guardian│ │ Earn │ │ Forge │ │Mem  │ │
│  └────┬────┘ └──┬───┘ └───┬───┘ └──┬──┘ │
│       └──────────┴─────────┴────────┘   │
│              sentinel_security (Shield)  │
│              zero-trust + audit log      │
└──────────────────┬──────────────────────┘
                   │ optional
                   ▼
         External APIs (bounty-targets, NVD, Ollama local)
```

## Threats & mitigations

| Threat | Mitigation |
|--------|------------|
| Silent cloud exfil | Layer 1 local-first audit; `SENTINEL_CLOUD_SYNC` opt-in |
| Cross-module privilege abuse | Layer 2 zero-trust policy per module |
| Plaintext secrets on disk | Layer 3 DPAPI / encrypted blob |
| Stolen vault files | Layer 4 AES-GCM (`SENTINEL_VAULT_ENCRYPT`) |
| Future quantum attacks | Layer 5 PQC hybrid abstraction |
| Compromised host | Layer 6 internal health audit |
| Tampered modules | Layer 7 signed manifest verification |
| Prompt injection / tool abuse | Layer 8 AI safety on API boundary |
| Repudiation | Layer 9 immutable hash-chained audit log |
| Binary/config tampering | Layer 10 baseline + restore hints |

## Out of scope

- Network perimeter firewall (OS responsibility)
- Physical device theft without encryption enabled
- User disabling `SENTINEL_SECURITY_STRICT`

## Adversary assumptions

- **Operator** is legitimate; wants frictionless scans (no auth popups)
- **External attacker** may supply malicious prompts or repos
- **Malware** may read disk — vault encryption reduces impact

## Residual risk

- Earn/Guardian **read** external JSON (bounty-targets, templates) — not uploads
- Browser sync (`workers/sync`) pulls conversations when sessions enabled — documented, not silent upload
- YubiKey/Passkey backends marked **planned** in secrets store (DPAPI active on Windows)

## Verification

Run `python run_security_audit.py` after each release; compare `module_manifest.json` to signed release artifacts.
