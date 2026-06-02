# Sentinel Security Health Report

| Field | Value |
|-------|-------|
| Generated | 2026-06-02T21:38:28.201247+00:00 |
| Host | Sleezy |
| Score | **HEALTHY** |

## Findings

No issues detected.

## Open Ports (sample)

- TCP    0.0.0.0:22             0.0.0.0:0              LISTENING       4464
- TCP    0.0.0.0:135            0.0.0.0:0              LISTENING       1692
- TCP    0.0.0.0:445            0.0.0.0:0              LISTENING       4
- TCP    0.0.0.0:3240           0.0.0.0:0              LISTENING       5328
- TCP    0.0.0.0:5040           0.0.0.0:0              LISTENING       11112
- TCP    0.0.0.0:5357           0.0.0.0:0              LISTENING       4
- TCP    0.0.0.0:7680           0.0.0.0:0              LISTENING       6444
- TCP    0.0.0.0:16034          0.0.0.0:0              LISTENING       27128
- TCP    0.0.0.0:16038          0.0.0.0:0              LISTENING       27128
- TCP    0.0.0.0:49664          0.0.0.0:0              LISTENING       1432
- TCP    0.0.0.0:49665          0.0.0.0:0              LISTENING       1204
- TCP    0.0.0.0:49666          0.0.0.0:0              LISTENING       2136
- TCP    0.0.0.0:49667          0.0.0.0:0              LISTENING       2712
- TCP    0.0.0.0:49668          0.0.0.0:0              LISTENING       3920
- TCP    0.0.0.0:49670          0.0.0.0:0              LISTENING       1396
- TCP    127.0.0.1:22           0.0.0.0:0              LISTENING       28344
- TCP    127.0.0.1:1420         0.0.0.0:0              LISTENING       27964
- TCP    127.0.0.1:5001         0.0.0.0:0              LISTENING       12788
- TCP    127.0.0.1:11434        0.0.0.0:0              LISTENING       30692
- TCP    127.0.0.1:16036        0.0.0.0:0              LISTENING       27128
- TCP    127.0.0.1:16037        0.0.0.0:0              LISTENING       27128
- TCP    127.0.0.1:16039        0.0.0.0:0              LISTENING       4728
- TCP    127.0.0.1:27015        0.0.0.0:0              LISTENING       4280
- TCP    127.0.0.1:45931        0.0.0.0:0              LISTENING       28344
- TCP    127.0.0.1:59382        0.0.0.0:0              LISTENING       27592
- TCP    172.22.48.1:139        0.0.0.0:0              LISTENING       4
- TCP    192.168.0.220:139      0.0.0.0:0              LISTENING       4
- TCP    [::]:22                [::]:0                 LISTENING       4464
- TCP    [::]:135               [::]:0                 LISTENING       1692
- TCP    [::]:445               [::]:0                 LISTENING       4

---

## Audit JSON

```json
{
  "bootstrap": {
    "integrity_ok": true,
    "local_first_passed": true,
    "cloud_sync_enabled": false,
    "vault": {
      "encryption_enabled": false,
      "key_available": false,
      "algorithm": "AES-256-GCM",
      "roots": [
        "C:\\Users\\pgg12\\Desktop\\SentinelAI\\memory\\vault",
        "C:\\Users\\pgg12\\Desktop\\SentinelAI\\memory",
        "C:\\Users\\pgg12\\Desktop\\SentinelAI\\data"
      ]
    },
    "pqc": {
      "kyber_available": false,
      "dilithium_available": false,
      "library": null,
      "hybrid_enabled": false
    },
    "secrets_backend": {
      "windows_dpapi_tpm": true,
      "user_secret": true,
      "yubikey": false,
      "passkey": false,
      "android_strongbox": false,
      "active": "windows_dpapi"
    }
  },
  "local_first": {
    "cloud_sync_enabled": false,
    "passed": true,
    "modules": [
      {
        "module": "guardian",
        "files_scanned": 17,
        "silent_risk": false,
        "external_calls": [],
        "upload_hints": [],
        "notes": []
      },
      {
        "module": "earn",
        "files_scanned": 12,
        "silent_risk": false,
        "external_calls": [
          "earn_diagnostics.py:55 urllib.request.urlopen",
          "earn_diagnostics.py:78 urllib.request.urlopen"
        ],
        "upload_hints": [],
        "notes": [
          "external HTTP (mostly read) \u2014 no upload patterns"
        ]
      },
      {
        "module": "forge",
        "files_scanned": 22,
        "silent_risk": false,
        "external_calls": [
          "godot_runtime.py:203 urllib.request.urlopen"
        ],
        "upload_hints": [],
        "notes": [
          "external HTTP (mostly read) \u2014 no upload patterns"
        ]
      },
      {
        "module": "vision",
        "files_scanned": 3,
        "silent_risk": false,
        "external_calls": [],
        "upload_hints": [],
        "notes": []
      },
      {
        "module": "memory",
        "files_scanned": 2,
        "silent_risk": false,
        "external_calls": [],
        "upload_hints": [],
        "notes": []
      }
    ],
    "sync_notes": [
      "workers/sync (browser pull \u2014 not cloud upload; requires explicit sessions)"
    ]
  },
  "zero_trust": {
    "guardian": {
      "filesystem": true,
      "network": true,
      "browser": false,
      "email": false,
      "ssh": false,
      "credentials": false
    },
    "earn": {
      "filesystem": true,
      "network": true,
      "browser": false,
      "email": false,
      "ssh": false,
      "credentials": false
    },
    "forge": {
      "filesystem": true,
      "network": false,
      "browser": false,
      "email": false,
      "ssh": false,
      "credentials": false
    },
    "vision": {
      "filesystem": true,
      "network": false,
      "browser": false,
      "email": false,
      "ssh": false,
      "credentials": false
    },
    "memory": {
      "filesystem": true,
      "network": false,
      "browser": false,
      "email": false,
      "ssh": false,
      "credentials": false
    },
    "shield": {
      "filesystem": true,
      "network": true,
      "browser": false,
      "email": false,
      "ssh": false,
      "credentials": true
    },
    "sync": {
      "filesystem": true,
      "network": true,
      "browser": true,
      "email": false,
      "ssh": false,
      "credentials": false
    }
  },
  "module_verify": [
    {
      "module": "guardian",
      "ok": true,
      "failures": []
    },
    {
      "module": "earn",
      "ok": true,
      "failures": []
    },
    {
      "module": "forge",
      "ok": true,
      "failures": []
    },
    {
      "module": "vision",
      "ok": true,
      "failures": []
    },
    {
      "module": "shield",
      "ok": true,
      "failures": []
    }
  ],
  "audit_chain_valid": true,
  "health": {
    "score": "HEALTHY",
    "findings": [],
    "open_ports_count": 44
  }
}
```
