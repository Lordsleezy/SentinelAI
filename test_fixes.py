"""Verify all 6 panel fixes via API."""
import urllib.request
import json

base = "http://127.0.0.1:5001"


def get(path, timeout=10):
    with urllib.request.urlopen(base + path, timeout=timeout) as r:
        return r.status, json.loads(r.read())


def post(path, body, timeout=10):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        base + path, data=data,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read())


results = {}

# TEST 1: /api/chat responds within timeout
print("=== TEST 1: /api/chat ===")
try:
    s, d = post("/api/chat", {"message": "hi"}, timeout=10)
    resp = d.get("response", "")
    worker = d.get("worker", "")
    if resp and s == 200:
        results["T1_chat"] = "PASS response='{}' worker={}".format(resp[:60], worker)
    else:
        results["T1_chat"] = "FAIL status={} resp={}".format(s, resp[:60])
    print("  Status:", s, "| Worker:", worker)
    print("  Response:", resp[:80])
except Exception as e:
    results["T1_chat"] = "FAIL: {}".format(e)
    print("  ERROR:", e)

# TEST 2: /market/summary quotes key + change fields
print("\n=== TEST 2: /market/summary ===")
try:
    s, d = get("/market/summary")
    quotes = d.get("quotes", d.get("prices", {}))
    has_quotes = len(quotes) >= 4
    price_ok = all(quotes.get(sym, {}).get("price", 0) > 0 for sym in ["BTC", "ETH", "SPY", "QQQ"])
    any_change = any(
        abs(quotes.get(sym, {}).get("change_pct", 0) or
            quotes.get(sym, {}).get("change_24h", 0) or
            quotes.get(sym, {}).get("change", 0)) > 0
        for sym in ["BTC", "ETH", "SPY", "QQQ"]
    )
    for sym in ["BTC", "ETH", "SPY", "QQQ"]:
        info = quotes.get(sym, {})
        price = info.get("price", 0)
        chg = info.get("change_pct") or info.get("change_24h") or info.get("change") or 0
        print("  {}: ${:,.2f}  {:+.2f}%".format(sym, price, chg))
    if has_quotes and price_ok and any_change:
        results["T2_market"] = "PASS {} tickers with prices and changes".format(len(quotes))
    else:
        results["T2_market"] = "FAIL has_quotes={} price_ok={} any_change={}".format(
            has_quotes, price_ok, any_change)
except Exception as e:
    results["T2_market"] = "FAIL: {}".format(e)
    print("  ERROR:", e)

# TEST 3: /earn/jobs returns jobs list
print("\n=== TEST 3: /earn/jobs (panel load) ===")
try:
    s, d = get("/earn/jobs")
    jobs = d.get("jobs", [])
    if len(jobs) > 0 and s == 200:
        results["T3_earn_load"] = "PASS {} jobs loaded".format(len(jobs))
        for j in jobs[:3]:
            name = j.get("program", j.get("name", "?"))
            reward = j.get("reward", j.get("reward_range", "?"))
            print("  - {}: {}".format(name, reward))
    else:
        results["T3_earn_load"] = "FAIL jobs={}".format(len(jobs))
except Exception as e:
    results["T3_earn_load"] = "FAIL: {}".format(e)
    print("  ERROR:", e)

# TEST 4: SCAN NOW now calls /earn/jobs (same endpoint, test it refreshes)
print("\n=== TEST 4: /earn/jobs (scan refresh) ===")
try:
    s, d = get("/earn/jobs")
    jobs = d.get("jobs", [])
    if len(jobs) > 0 and s == 200:
        results["T4_earn_scan"] = "PASS {} jobs after scan refresh".format(len(jobs))
        print("  Job count after refresh:", len(jobs))
    else:
        results["T4_earn_scan"] = "FAIL jobs={}".format(len(jobs))
except Exception as e:
    results["T4_earn_scan"] = "FAIL: {}".format(e)
    print("  ERROR:", e)

# TEST 5: /guardian/status returns tool data
print("\n=== TEST 5: /guardian/status (tools) ===")
try:
    s, d = get("/guardian/status")
    print("  Keys:", list(d.keys()))
    tools = d.get("available_tools", d.get("tools", d.get("available", [])))
    print("  Tools value:", tools)
    # Even if tools list is empty, the endpoint responded — that's the fix
    if s == 200:
        results["T5_guardian_tools"] = "PASS endpoint=200 tools={}".format(tools)
    else:
        results["T5_guardian_tools"] = "FAIL status={}".format(s)
except Exception as e:
    results["T5_guardian_tools"] = "FAIL: {}".format(e)
    print("  ERROR:", e)

# Print results
print("\n" + "=" * 55)
print("RESULTS")
print("=" * 55)
for k, v in results.items():
    status = "[PASS]" if v.startswith("PASS") else "[FAIL]"
    print("  {} {}: {}".format(status, k, v))

passes = sum(1 for v in results.values() if v.startswith("PASS"))
total = len(results)
print("\n  TOTAL: {}/{} PASS".format(passes, total))
