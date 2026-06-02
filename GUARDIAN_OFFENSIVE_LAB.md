# Guardian Offensive Lab

Ethical penetration testing module for **closed, authorized lab environments** only.

## What it does

When Guardian is in **ATTACK** mode and the closed lab is acknowledged, the assessment pipeline adds:

| Stage | Purpose |
|-------|---------|
| **Network Penetration** | `nmap` service discovery (top ports, `-sV`) |
| **Credential Audit** | Rate-limited `hydra` against lab wordlist (`memory/vault/guardian_lab/wordlists/`) |
| **Backdoor Detection** | Suspicious paths + Nuclei tags (`backdoor`, `webshell`, `malware`, `persistence`) |
| **Exploit Research** | Metasploit CVE search (reference only — no auto-exploit) |

## Safety gates

1. `config/guardian_config.json` → `offensive_lab.closed_lab_acknowledged` must be `true`
2. Guardian mode must be **ATTACK**
3. Target must be **Trusted** or on a **private/lab** network (`10.x`, `192.168.x`, `172.16–31`, `127.x`, `localhost`)

Public targets are blocked until added under **Trusted Targets**.

## How to run

1. Open Guardian → **ATTACK**
2. Confirm closed lab (panel **ACK CLOSED LAB** or API below)
3. Add lab target under **Trusted Targets** (e.g. `192.168.1.10` or `lab.local`)
4. Chat example: `pentest 192.168.1.10` or `scan lab.local password audit`

## Configuration

```json
"offensive_lab": {
  "enabled": true,
  "closed_lab_acknowledged": true,
  "require_attack_mode": true,
  "credential_audit": { "enabled": true, "max_duration_sec": 90 },
  "network_penetration": { "enabled": true, "top_ports": 1000 },
  "backdoor_detection": { "enabled": true }
}
```

Custom passwords for lab: edit `memory/vault/guardian_lab/wordlists/lab_common.txt` (keep lists small).

## API

- `GET /api/guardian/offensive-lab/status?target=192.168.1.1`
- `POST /api/guardian/offensive-lab/acknowledge`

## Optional tools

Install on the lab host or WSL:

- `nmap` — network penetration
- `hydra` — credential audit
- `msfconsole` — exploit research search
- ProjectDiscovery `nuclei` — backdoor/malware templates

## What it does **not** do

- Deploy backdoors or malware
- Unlimited password cracking against internet hosts
- Auto-run exploits without explicit operator control
- Bypass trusted-target / private-network rules

Findings are stored in the Guardian Findings DB and included in the final report under **Offensive Lab**.
