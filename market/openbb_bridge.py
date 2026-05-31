"""OpenBB bridge — read-only financial data (dry_run guard enforced).

Minimal scaffold. ``get_quote`` and ``get_news`` return ``None`` when OpenBB is
not installed; no exception is raised. Live order routing is intentionally
absent.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DRY_RUN = os.getenv("SENTINEL_MARKET_LIVE", "false").lower() != "true"


def _openbb_available() -> bool:
    try:
        import openbb  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False


def get_quote(symbol: str) -> Optional[Dict[str, Any]]:
    """Return the latest quote for ``symbol`` or ``None`` on any failure."""
    if not _openbb_available():
        logger.debug("openbb not installed; quote unavailable")
        return None
    try:
        from openbb import obb  # type: ignore
        quote = obb.equity.price.quote(symbol)
        return {"symbol": symbol, "data": getattr(quote, "results", quote)}
    except Exception as exc:
        logger.debug("get_quote(%s) failed: %s", symbol, exc)
        return None


def place_order(*_args, **_kwargs) -> Dict[str, Any]:
    """Order placement is dry_run only. Always returns a refusal payload."""
    if DRY_RUN:
        return {"status": "dry_run", "executed": False,
                "message": "Sentinel Market is dry_run; no live order placed"}
    # Even when live is enabled, this scaffold does not route real orders.
    return {"status": "unsupported", "executed": False,
            "message": "Live order routing is not implemented in this build"}
