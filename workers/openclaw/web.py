"""
OpenClaw Web — Web search and page fetching
"""
import os
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


def search_web(query: str, num_results: int = 5) -> Dict[str, Any]:
    """Search the web using Brave Search API"""
    api_key = os.getenv('BRAVE_API_KEY')

    if not api_key:
        return {"error": "BRAVE_API_KEY not set", "results": []}

    if not HTTPX_AVAILABLE:
        return {"error": "httpx not installed", "results": []}

    try:
        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": api_key
        }
        params = {
            "q": query,
            "count": num_results
        }

        with httpx.Client() as client:
            response = client.get(url, headers=headers, params=params, timeout=10.0)
            response.raise_for_status()

            data = response.json()
            results = []

            for item in data.get('web', {}).get('results', []):
                results.append({
                    'title': item.get('title'),
                    'url': item.get('url'),
                    'description': item.get('description')
                })

            return {"error": None, "results": results}

    except Exception as e:
        logger.error(f"Brave search failed: {e}")
        return {"error": str(e), "results": []}


def fetch_page(url: str) -> Dict[str, Any]:
    """Fetch a web page and return its text content"""
    if not PLAYWRIGHT_AVAILABLE:
        return {"error": "playwright not installed", "text": ""}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until='domcontentloaded', timeout=15000)

            # Extract text content
            text = page.inner_text('body')

            browser.close()

            return {"error": None, "text": text}

    except Exception as e:
        logger.error(f"Page fetch failed: {e}")
        return {"error": str(e), "text": ""}


def summarize_page(url: str) -> Dict[str, Any]:
    """Fetch a page and summarize it using Ollama"""
    # Fetch the page
    fetch_result = fetch_page(url)

    if fetch_result.get('error'):
        return {"error": fetch_result['error'], "summary": ""}

    text = fetch_result['text']

    if not text or len(text) < 50:
        return {"error": "Page text too short or empty", "summary": ""}

    # Summarize with Ollama
    if not HTTPX_AVAILABLE:
        return {"error": "httpx not installed", "summary": ""}

    try:
        ollama_host = os.getenv('OLLAMA_HOST', 'http://127.0.0.1:11434')

        # Try llava first (vision model can handle text), fallback to qwen2.5-coder
        models_to_try = ['llava', 'qwen2.5-coder:14b', 'qwen2.5-coder']

        for model in models_to_try:
            try:
                with httpx.Client() as client:
                    prompt = f"Summarize this web page in 2-3 sentences:\n\n{text[:4000]}"

                    response = client.post(
                        f"{ollama_host}/api/generate",
                        json={
                            "model": model,
                            "prompt": prompt,
                            "stream": False
                        },
                        timeout=30.0
                    )

                    if response.status_code == 200:
                        data = response.json()
                        summary = data.get('response', '').strip()
                        return {"error": None, "summary": summary}

            except Exception:
                continue

        return {"error": "All Ollama models failed", "summary": ""}

    except Exception as e:
        logger.error(f"Summarization failed: {e}")
        return {"error": str(e), "summary": ""}
