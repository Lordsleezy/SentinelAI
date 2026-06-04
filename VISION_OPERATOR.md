# Vision Operator (Phase 2C)

**Module:** `core/sentinelscrub/operator/browser/vision_bridge.py`  
**Integration:** `BrowserOperator.smart_click()` / `smart_fill()`

## Sentinel Vision

Uses **Ollama** vision model (default `llava`) — same stack as Sentinel home camera描述.

```
OLLAMA_HOST=http://127.0.0.1:11434
SENTINEL_VISION_MODEL=llava
```

`vision_available()` probes `/api/tags` for model presence.

## Capabilities

| Function | Purpose |
|----------|---------|
| `analyze_screenshot(path, prompt)` | General page understanding |
| `find_click_target(path, description)` | Locate buttons, login, errors |
| `identify_page_elements(path)` | List TYPE \| LABEL elements |

## Browser fallback order

`smart_click(selector=, text=, vision_target=)`:

1. **CSS selector** — Playwright click  
2. **Text** — `get_by_text()`  
3. **Vision** — screenshot → llava → suggested labels → text click  

Enables operation on **unknown websites** when selectors are unavailable.

## Failure capture

On pipeline errors, `failure_capture` stores screenshot path for diagnosis and vision replay.

## Requirements

- Ollama running locally  
- Vision model pulled: `ollama pull llava`  
- Playwright for screenshots  

Without vision, steps 1–2 still work; step 3 returns actionable error.
