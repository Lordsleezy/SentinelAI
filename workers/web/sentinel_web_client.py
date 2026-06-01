"""
sentinel_web_client.py — SentinelAI client for the SentinelWeb microservice.

SentinelWeb (port 8766) provides:
  POST /query              Natural language web query → answer
  POST /query/compare      Multi-site price comparison
  POST /credentials/save   Save encrypted site credentials
  GET  /credentials/list   List saved site names
  GET  /health             Health / status check
"""
CAPABILITY_DESCRIPTION = (
    "Web automation — browse websites, compare prices, check availability, "
    "login to services, find product information"
)

import logging
from typing import List, Optional

import httpx

logger = logging.getLogger(__name__)

SENTINEL_WEB_URL = "http://localhost:8766"
_DEFAULT_TIMEOUT = 60.0
_COMPARE_TIMEOUT = 120.0


# ── Core query ────────────────────────────────────────────────────────────────

async def query_web(
    natural_language_query: str,
    url: Optional[str] = None,
    site_name: Optional[str] = None,
) -> dict:
    """Send a natural language query to SentinelWeb.

    Returns a dict with: answer, source_url, confidence, execution_time,
    cached, login_used, error.
    """
    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            payload: dict = {"query": natural_language_query}
            if url:
                payload["url"] = url
            if site_name:
                payload["site_name"] = site_name
            r = await client.post(f"{SENTINEL_WEB_URL}/query", json=payload)
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        logger.error("SentinelWeb query HTTP %s: %s", e.response.status_code, e)
        return {"error": f"HTTP {e.response.status_code}", "answer": None}
    except Exception as e:
        logger.error("SentinelWeb query failed: %s", e)
        return {"error": str(e), "answer": None}


async def compare_prices(
    product_query: str,
    sites: Optional[List[str]] = None,
) -> dict:
    """Compare prices across multiple sites via /query/compare.

    Returns the raw comparison dict from SentinelWeb.
    """
    default_sites = ["amazon.com", "walmart.com", "bestbuy.com", "target.com"]
    try:
        async with httpx.AsyncClient(timeout=_COMPARE_TIMEOUT) as client:
            payload = {
                "query": product_query,
                "sites": sites or default_sites,
            }
            r = await client.post(f"{SENTINEL_WEB_URL}/query/compare", json=payload)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        logger.error("SentinelWeb compare failed: %s", e)
        return {"error": str(e)}


async def save_site_credentials(site: str, username: str, password: str) -> dict:
    """Save encrypted credentials for a site in SentinelWeb's credential store."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{SENTINEL_WEB_URL}/credentials/save",
                json={"site": site, "username": username, "password": password},
            )
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {"error": str(e)}


async def list_saved_sites() -> List[str]:
    """Return the list of sites SentinelWeb has credentials for."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{SENTINEL_WEB_URL}/credentials/list")
            r.raise_for_status()
            return r.json().get("sites", [])
    except Exception:
        return []


# ── Health check ──────────────────────────────────────────────────────────────

async def is_available() -> bool:
    """Return True if SentinelWeb is reachable."""
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.get(f"{SENTINEL_WEB_URL}/health")
            return r.status_code == 200
    except Exception:
        return False


async def get_health() -> dict:
    """Return full health dict from SentinelWeb."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{SENTINEL_WEB_URL}/health")
            r.raise_for_status()
            return r.json()
    except Exception as e:
        return {"status": "offline", "error": str(e)}


# ── Purchase intent helper ────────────────────────────────────────────────────

async def find_product_to_buy(product_query: str) -> dict:
    """
    Find the best price and URL for a product the user wants to buy.
    Returns: {found, product, price, site, url, all_prices}
    This does NOT complete the purchase — it only finds the information needed
    for the approval flow.
    """
    compare = await compare_prices(product_query)

    if "error" in compare and not compare.get("site_results"):
        # Fall back to a single Amazon query
        result = await query_web(f"price and buy link for {product_query}", site_name="amazon")
        return {
            "found": bool(result.get("answer")),
            "product": product_query,
            "price": None,
            "site": "Amazon",
            "url": result.get("source_url"),
            "answer": result.get("answer"),
            "all_prices": [],
        }

    # Parse comparison results — SentinelWeb returns site_results list
    site_results = compare.get("site_results", [])
    if not site_results:
        return {"found": False, "product": product_query, "error": compare.get("error")}

    # Find cheapest site with a valid price
    best = None
    all_prices = []
    for sr in site_results:
        price_raw = sr.get("price") or sr.get("answer", "")
        all_prices.append({"site": sr.get("site"), "price": price_raw, "url": sr.get("url")})
        if price_raw and not best:
            best = sr

    if not best:
        best = site_results[0]

    return {
        "found": True,
        "product": product_query,
        "price": best.get("price") or best.get("answer"),
        "site": best.get("site", ""),
        "url": best.get("url") or best.get("source_url"),
        "all_prices": all_prices,
        "summary": compare.get("summary", ""),
    }
