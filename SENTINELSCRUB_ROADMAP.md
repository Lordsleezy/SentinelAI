# SentinelScrub Roadmap

## Shipped (foundation)

- [x] Core package `core/sentinelscrub/` with planner, operators, vault, memory, verify, repair, providers  
- [x] Goal engine + SQLite persistence + execution feed  
- [x] Research engine (provider knowledge + HTTP fetch)  
- [x] Playwright browser operator (when installed)  
- [x] Desktop operator (CLI + optional pyautogui)  
- [x] Encrypted account vault  
- [x] Approval gate + REST API  
- [x] 8 provider stubs with real `research()` / `verify()`  
- [x] Settings → SentinelScrub UI + Socket.IO feed  
- [x] Safe boot (non-fatal init)  

## Phase 2 — Chat & routing

- [ ] Route natural language goals from `/api/chat` to SentinelScrub when intent matches  
- [ ] Approval dialogs in floating chat bubbles  
- [ ] Goal status summaries in Sentinel voice (no internal worker names)

## Phase 3 — Provider depth

- [ ] Amazon: search → compare → checkout automation post-approval  
- [ ] Supabase: CLI/API project creation  
- [ ] Stripe: product + webhook setup  
- [ ] Cloudflare: DNS + domain renew via API  
- [ ] GitHub / Netlify deploy pipelines  

## Phase 4 — Vision & resilience

- [ ] Vision-assisted browser (screenshot → element locate)  
- [ ] Persist trusted providers to disk  
- [ ] Receipt / artifact registry integration  
- [ ] Reversible action journal  

## Phase 5 — Platform

- [ ] Linux / macOS desktop operator parity  
- [ ] Android operator bridge  
- [ ] Headed browser mode for user takeover  

## Dependencies

```bash
pip install playwright httpx
playwright install chromium
# optional:
pip install pyautogui
```
