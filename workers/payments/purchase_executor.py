"""
purchase_executor.py — Executes approved purchases via SentinelWeb + credential store.

Flow:
  1. User says "buy X" → /api/chat routes to find_product_to_buy()
  2. SentinelWeb finds price, URL, site via /query/compare
  3. Returns requires_approval=True with product details → orb shows approval modal
  4. User approves → /payments/execute called
  5. Executor checks spending limits, retrieves payment details from vault
  6. Sends credentials + product URL to SentinelWeb for checkout completion
  7. Logs transaction to memory vault

Note: SentinelWeb's browser automation handles the actual checkout page interaction
using credentials saved in its own credential store.
"""
CAPABILITY_DESCRIPTION = "Executes approved purchases using SentinelWeb browser automation and saved payment methods"

import logging
from datetime import datetime
from typing import Optional

from workers.payments.payment_manager import PaymentManager

logger = logging.getLogger(__name__)

SENTINEL_WEB_URL = "http://localhost:8766"


class PurchaseExecutor:
    def __init__(self):
        self.payment_mgr = PaymentManager()

    # ── Pre-purchase: find best deal ──────────────────────────────────────────

    async def find_and_stage(self, product_query: str) -> dict:
        """
        Find the best price for a product and return a staged purchase approval.
        Does NOT complete the purchase.
        """
        from workers.web.sentinel_web_client import find_product_to_buy
        found = await find_product_to_buy(product_query)

        if not found.get("found"):
            return {
                "requires_approval": False,
                "error": found.get("error", "Could not find product information."),
            }

        default_method = self.payment_mgr.get_default_method()
        methods = self.payment_mgr.get_payment_methods()

        return {
            "requires_approval": True,
            "product": found.get("product", product_query),
            "price": found.get("price"),
            "site": found.get("site"),
            "url": found.get("url"),
            "all_prices": found.get("all_prices", []),
            "summary": found.get("summary") or found.get("answer", ""),
            "payment_methods": methods,
            "default_method_id": (default_method or {}).get("id"),
            "message": _format_approval_message(found),
        }

    # ── Execute approved purchase ─────────────────────────────────────────────

    async def execute_purchase(self, approval_data: dict) -> dict:
        """
        Execute a purchase after user approval.
        approval_data: {product, price, site, url, method_id, ...}
        """
        product = approval_data.get("product", "Unknown item")
        price_str = str(approval_data.get("price") or "0").replace("$", "").replace(",", "")
        site = approval_data.get("site", "")
        product_url = approval_data.get("url", "")
        method_id = approval_data.get("method_id")

        # Resolve payment method
        if not method_id:
            default = self.payment_mgr.get_default_method()
            if not default:
                return {
                    "status": "error",
                    "message": "No payment method configured. Add one in Settings (click the 💳 icon).",
                }
            method_id = default["id"]

        method = next((m for m in self.payment_mgr.get_payment_methods() if m["id"] == method_id), {})

        # Check spending limit
        try:
            amount = float(price_str) if price_str else 0.0
        except ValueError:
            amount = 0.0

        if amount > 0:
            limit_check = self.payment_mgr.check_spending_limit(amount)
            if not limit_check["allowed"]:
                return {"status": "error", "message": limit_check["reason"]}

        # Get raw payment details (never logged)
        payment_details = self.payment_mgr.get_details(method_id)

        # Attempt checkout via SentinelWeb
        checkout_result = await self._attempt_checkout(
            product=product,
            product_url=product_url,
            site=site,
            payment_details=payment_details,
            method_type=method.get("type", ""),
        )

        status = checkout_result.get("status", "error")

        # Log transaction regardless of outcome
        self.payment_mgr.log_transaction({
            "id": checkout_result.get("order_id", f"tx-{datetime.now().strftime('%Y%m%d%H%M%S')}"),
            "merchant": site,
            "amount": amount,
            "currency": "USD",
            "product": product,
            "status": status,
            "payment_method_nickname": method.get("nickname", "Unknown"),
            "order_number": checkout_result.get("order_number"),
            "url": product_url,
        })

        return {
            "status": status,
            "message": checkout_result.get("message", ""),
            "order_number": checkout_result.get("order_number"),
            "product_url": product_url,
        }

    async def _attempt_checkout(
        self,
        product: str,
        product_url: str,
        site: str,
        payment_details: dict,
        method_type: str,
    ) -> dict:
        """
        Use SentinelWeb's browser to attempt checkout.

        For Amazon/Walmart/Target/BestBuy: SentinelWeb uses saved site credentials
        (email/password in its credential store) + the saved card on the account.
        For PayPal / other methods: browser navigates to checkout and applies the method.
        """
        import httpx

        if not product_url:
            return {
                "status": "error",
                "message": f"No product URL found. Search {site} manually for '{product}'.",
            }

        # Determine which credential key SentinelWeb uses for this site
        site_lower = site.lower().replace(" ", "").replace(".", "")
        cred_site_map = {
            "amazon": "amazon",
            "walmart": "walmart",
            "bestbuy": "bestbuy",
            "target": "target",
        }
        cred_key = next((v for k, v in cred_site_map.items() if k in site_lower), None)

        # If the payment method IS the site account (e.g. amazon_pay for Amazon), push
        # those credentials into SentinelWeb's store first.
        if method_type == "amazon_pay" and cred_key == "amazon" and payment_details.get("email"):
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    await client.post(
                        f"{SENTINEL_WEB_URL}/credentials/save",
                        json={
                            "site": "amazon",
                            "username": payment_details["email"],
                            "password": payment_details.get("password", ""),
                        },
                    )
            except Exception as e:
                logger.warning("Could not push Amazon credentials to SentinelWeb: %s", e)

        # Run a checkout query via SentinelWeb natural language
        checkout_query = (
            f"Add to cart and complete checkout for {product} at this URL: {product_url}. "
            f"Use saved account credentials to log in and complete purchase."
        )

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                r = await client.post(
                    f"{SENTINEL_WEB_URL}/query",
                    json={"query": checkout_query, "url": product_url, "site_name": cred_key or site_lower},
                )
                result = r.json()

                answer = result.get("answer", "")
                if any(kw in answer.lower() for kw in ["order", "confirm", "placed", "success", "purchased"]):
                    return {
                        "status": "success",
                        "message": f"Purchase complete! {answer}",
                        "order_number": _extract_order_number(answer),
                    }
                else:
                    # Browser ran but didn't confirm checkout — return the URL for manual completion
                    return {
                        "status": "manual_required",
                        "message": (
                            f"SentinelWeb navigated to {site} but could not auto-complete checkout "
                            f"(may require 2FA or CAPTCHA). "
                            f"Complete your purchase here: {product_url}"
                        ),
                    }
        except Exception as e:
            logger.error("Checkout attempt failed: %s", e)
            return {
                "status": "manual_required",
                "message": (
                    f"Could not complete automatic checkout: {e}. "
                    f"Complete your purchase manually: {product_url}"
                ),
            }

    # ── Booking ───────────────────────────────────────────────────────────────

    async def find_and_stage_booking(self, booking_query: str) -> dict:
        """Find booking options (flights, hotels, restaurants) and stage approval."""
        from workers.web.sentinel_web_client import query_web
        result = await query_web(booking_query)
        if result.get("error"):
            return {"requires_approval": False, "error": result["error"]}
        return {
            "requires_approval": True,
            "booking_type": "general",
            "query": booking_query,
            "result": result.get("answer"),
            "url": result.get("source_url"),
            "message": f"Found: {result.get('answer', '')}. Proceed with booking?",
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_approval_message(found: dict) -> str:
    price = found.get("price") or "unknown price"
    site = found.get("site") or "unknown site"
    product = found.get("product", "item")
    msg = f"Found {product} for {price} on {site}."
    if found.get("all_prices") and len(found["all_prices"]) > 1:
        others = ", ".join(
            f"{p['site']}: {p['price']}" for p in found["all_prices"][1:3] if p.get("price")
        )
        if others:
            msg += f" Also available: {others}."
    msg += " Approve purchase?"
    return msg


def _extract_order_number(text: str) -> Optional[str]:
    import re
    m = re.search(r"(?:order|#|number)[:\s#]*([A-Z0-9\-]{6,20})", text, re.I)
    return m.group(1) if m else None
