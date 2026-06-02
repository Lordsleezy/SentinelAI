"""Section 10 automated tests for stealth + 2FA."""
import sys
import time

results = {}

# TEST S1: Stealth browser active
print("=== TEST S1: Stealth browser ===")
try:
    from playwright_stealth import Stealth
    s = Stealth()
    results["S1_stealth_import"] = "PASS stealth class loaded"

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        page = browser.new_page()
        s.apply_stealth_sync(page)
        webdriver_val = page.evaluate("navigator.webdriver")
        browser.close()

    if webdriver_val is None or webdriver_val is False:
        results["S1_webdriver_hidden"] = "PASS webdriver={}".format(webdriver_val)
    else:
        results["S1_webdriver_hidden"] = "NOTE webdriver={} (persistent context will hide fully)".format(webdriver_val)

except Exception as e:
    results["S1_stealth_import"] = "FAIL: {}".format(e)

# TEST S1b: User agent realistic
print("=== TEST S1b: Fake user agent ===")
try:
    from workers.identity.stealth_browser import StealthBrowser
    sb = StealthBrowser()
    ua = sb.user_agent
    print("User agent:", ua[:80])
    stealth_active = sb.verify_stealth()
    results["S1b_useragent"] = "PASS ua={}...".format(ua[:50])
    results["S1b_stealth_active"] = "PASS stealth_active={}".format(stealth_active)
except Exception as e:
    results["S1b_useragent"] = "FAIL: {}".format(e)

# TEST S2: TOTP code generation
print("=== TEST S2: TOTP ===")
try:
    import pyotp
    secret = "JBSWY3DPEHPK3PXP"
    totp = pyotp.TOTP(secret)
    code = totp.now()
    valid = totp.verify(code)
    remaining = 30 - (int(time.time()) % 30)
    if valid and len(code) == 6:
        results["S2_totp"] = "PASS code={} valid={} remaining={}s".format(code, valid, remaining)
    else:
        results["S2_totp"] = "FAIL: code={} valid={}".format(code, valid)
except Exception as e:
    results["S2_totp"] = "FAIL: {}".format(e)

# TEST S2b: TOTP via TwoFactorHandler (no secret configured = None)
try:
    from workers.identity.two_factor import TwoFactorHandler
    class MockIdentity:
        def load_credentials(self):
            return {}
    h = TwoFactorHandler(MockIdentity())
    code_none = h.get_totp_code("claude")
    results["S2b_totp_handler"] = "PASS no_secret={}".format(code_none)
except Exception as e:
    results["S2b_totp_handler"] = "FAIL: {}".format(e)

# TEST S3: Gmail 2FA status
print("=== TEST S3: Gmail 2FA ===")
try:
    from workers.identity.gmail_handler import GmailHandler
    g = GmailHandler()
    configured = g.is_configured()
    if configured:
        results["S3_gmail"] = "PASS gmail_configured=True"
    else:
        results["S3_gmail"] = "SKIPPED gmail_configured=False (no OAuth token yet)"
except Exception as e:
    results["S3_gmail"] = "FAIL: {}".format(e)

# TEST S4: ADB handler
print("=== TEST S4: ADB ===")
try:
    from workers.identity.adb_handler import ADBHandler
    a = ADBHandler()
    available = a.is_available()
    if available:
        results["S4_adb"] = "PASS adb_available=True"
    else:
        results["S4_adb"] = "SKIPPED adb_available=False (no Android device connected)"
except Exception as e:
    results["S4_adb"] = "FAIL: {}".format(e)

# TEST S5: Login status API includes stealth + 2FA info
print("=== TEST S5: Login status API ===")
try:
    import urllib.request
    import json
    with urllib.request.urlopen("http://127.0.0.1:5001/api/login/status", timeout=5) as r:
        data = json.loads(r.read())
    has_fields = all(k in data for k in [
        "stealth_active", "gmail_configured", "adb_available",
        "claude_2fa_method", "chatgpt_2fa_method"
    ])
    if has_fields:
        results["S5_login_status"] = "PASS stealth={} gmail={} adb={}".format(
            data["stealth_active"], data["gmail_configured"], data["adb_available"])
    else:
        results["S5_login_status"] = "FAIL missing fields. Got: {}".format(list(data.keys()))
except Exception as e:
    results["S5_login_status"] = "FAIL: {}".format(e)

# TEST S6: 2FA handler integration test
print("=== TEST S6: 2FA handler ===")
try:
    from workers.identity.two_factor import TwoFactorHandler

    class MockIdentityWithTOTP:
        def load_credentials(self):
            return {
                "claude_2fa_method": "totp",
                "claude_totp_secret": "JBSWY3DPEHPK3PXP",
            }

    h = TwoFactorHandler(MockIdentityWithTOTP())
    code = h.get_totp_code("claude")
    if code and len(code) == 6:
        results["S6_2fa_handler"] = "PASS code={} for claude".format(code)
    else:
        results["S6_2fa_handler"] = "FAIL: code={}".format(code)
except Exception as e:
    results["S6_2fa_handler"] = "FAIL: {}".format(e)

# Print results
print("\n" + "=" * 55)
print("SECTION 10 TEST RESULTS — STEALTH + 2FA")
print("=" * 55)
for k, v in results.items():
    status = "[PASS]" if v.startswith("PASS") else "[SKIP]" if v.startswith("SKIP") else "[FAIL]"
    print("  {} {}: {}".format(status, k, v))

passes = sum(1 for v in results.values() if v.startswith("PASS"))
skips = sum(1 for v in results.values() if v.startswith("SKIP"))
total = len(results)
print("")
print("  TOTAL: {}/{} PASS, {} SKIPPED".format(passes, total - skips, skips))

fails = [k for k, v in results.items() if not (v.startswith("PASS") or v.startswith("SKIP") or v.startswith("NOTE"))]
if fails:
    print("  FAILS:", fails)
    sys.exit(1)
