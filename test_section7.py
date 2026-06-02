"""Section 7 automated test suite."""
import urllib.request
import json
import sys

base = "http://127.0.0.1:5001"


def get(path, timeout=8):
    with urllib.request.urlopen(base + path, timeout=timeout) as r:
        return json.loads(r.read())


def post(path, body=None, timeout=8):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        base + path, data=data,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


results = {}


# TEST 1: Login status
try:
    d = get("/api/login/status")
    results["T1_login_status"] = "PASS configured={} user={}".format(
        d["configured"], d.get("user_name"))
except Exception as e:
    results["T1_login_status"] = "FAIL: {}".format(e)

# TEST 2: Memory stats
try:
    d = get("/memory/stats")
    results["T2_memory_stats"] = "PASS hot={} total={}MB".format(
        d["hot_entries"], d["total_size_mb"])
except Exception as e:
    results["T2_memory_stats"] = "FAIL: {}".format(e)

# TEST 3: Memory recall
try:
    d = get("/memory/recall?q=sentinel&limit=3")
    results["T3_memory_recall"] = "PASS results={}".format(d["count"])
except Exception as e:
    results["T3_memory_recall"] = "FAIL: {}".format(e)

# TEST 4: Sync status
try:
    d = get("/sync/status")
    results["T4_sync_status"] = "PASS next_sync={}".format(d["next_sync_in"])
except Exception as e:
    results["T4_sync_status"] = "FAIL: {}".format(e)

# TEST 5: Sync trigger
try:
    d = post("/sync/trigger")
    results["T5_sync_trigger"] = "PASS status={}".format(d["status"])
except Exception as e:
    results["T5_sync_trigger"] = "FAIL: {}".format(e)

# TEST 6: Sync conversations list
try:
    d = get("/sync/conversations")
    results["T6_sync_conversations"] = "PASS count={}".format(d["count"])
except Exception as e:
    results["T6_sync_conversations"] = "FAIL: {}".format(e)

# TEST 7: Memory from source
try:
    d = get("/memory/from/claude")
    results["T7_memory_from_claude"] = "PASS results={}".format(d["count"])
except Exception as e:
    results["T7_memory_from_claude"] = "FAIL: {}".format(e)

# TEST 8: Chat basic
try:
    d = post("/api/chat", {"message": "hello"})
    results["T8_chat_basic"] = "PASS worker={}".format(d.get("worker"))
except Exception as e:
    results["T8_chat_basic"] = "FAIL: {}".format(e)

# TEST 9: Login save
try:
    d = post("/api/login/save", {
        "user_name": "Paul",
        "user_email": "paul@test.com",
        "claude_email": "",
        "claude_password": "",
        "chatgpt_email": "",
        "chatgpt_password": "",
    })
    results["T9_login_save"] = "PASS status={}".format(d.get("status"))
except Exception as e:
    results["T9_login_save"] = "FAIL: {}".format(e)

# TEST 10: Login status after save
try:
    d = get("/api/login/status")
    results["T10_login_status_after"] = "PASS configured={} user={}".format(
        d["configured"], d.get("user_name"))
except Exception as e:
    results["T10_login_status_after"] = "FAIL: {}".format(e)

# TEST 11: Memory stats after login save
try:
    d = get("/memory/stats")
    results["T11_memory_stats_final"] = "PASS hot={} cold={} total={}MB".format(
        d["hot_entries"], d["cold_files"], d["total_size_mb"])
except Exception as e:
    results["T11_memory_stats_final"] = "FAIL: {}".format(e)

# TEST 12: ChromaDB no deprecation (check memory recall works)
try:
    d = get("/memory/recall?q=trading&limit=5")
    results["T12_chromadb_no_errors"] = "PASS recall_ok results={}".format(d["count"])
except Exception as e:
    results["T12_chromadb_no_errors"] = "FAIL: {}".format(e)

print("=" * 50)
print("SECTION 7 TEST RESULTS")
print("=" * 50)
for k, v in results.items():
    status = "[PASS]" if v.startswith("PASS") else "[FAIL]"
    print("  {} {}: {}".format(status, k, v))

passes = sum(1 for v in results.values() if v.startswith("PASS"))
total = len(results)
print("")
print("  TOTAL: {}/{} PASS".format(passes, total))

if passes < total:
    sys.exit(1)
