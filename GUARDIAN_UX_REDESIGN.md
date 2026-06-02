# Guardian UX Redesign

## Summary

Guardian is now a **chat-first security copilot** with a neutral premium theme (#0B0B0B / #141414), matching ChatGPT/Cursor-style UX. Advanced controls live in **⚙ Guardian Settings**.

## Layout

- Header: Guardian + Settings
- Mode chips: Defend / Attack / Forensics
- Conversation (primary)
- Input + Send

## Moved to Settings

- Tool status & bootstrap repair
- Guardian Brain (runtime / models / install)
- Trusted targets
- Threat intel notes
- Crypto intel roadmap note
- Findings center preview
- Technical log
- Offensive lab acknowledgement

## Socket events

- `guardian_response` includes `chat_line` (humanized) + `response` (full detail)
- `guardian_bootstrap_update` / `guardian_bootstrap_complete` refresh tools in settings

## Unchanged

- All `/guardian/*` and `/api/guardian/*` routes preserved
- Scan pipeline and APIs intact
- Sentinel Orb visuals untouched
