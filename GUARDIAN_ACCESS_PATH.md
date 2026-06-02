# Guardian Access Path Analysis

Find ways into a **network or system via exploitable weaknesses** — without brute force or backdoors.

## Example commands

Tell Guardian (include the target):

- `Find a way to access 192.168.1.50 by exploiting weaknesses`
- `Guardian, get into lab.target.com — find a bug that allows access, no brute force`
- `Break into https://staging.example.com without backdoors`

## What runs

1. Full recon pipeline (subdomains, httpx, crawl, Nuclei, ZAP, threat intel)
2. **Access Path Analysis** stage:
   - Extra Nuclei pass with access tags: RCE, SQLi, auth-bypass, SSRF, LFI, IDOR, CVE, etc.
   - Correlates findings into prioritized **access vectors**
   - Guardian AI **exploitation research plan** (validation steps, not malware)
3. Skips **Offensive Lab** credential brute force when in access-path mode
4. Final report section: **Access Path Analysis**

## Output

For each vector:

- Category (RCE, SQLi, auth bypass, …)
- Severity
- Target URL
- Suggested **validation** step (minimal PoC for authorized/bounty scope)

## Bug bounty use

Use vectors + plan to:

1. Manually confirm the bug
2. Capture HTTP evidence
3. Submit through Earn / your platform template

## Policy

Guardian will **not** run hydra/password brute force or deploy backdoors in this mode. For password spraying, use Offensive Lab in ATTACK mode on **private lab** targets only (separate workflow).
