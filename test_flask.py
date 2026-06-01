import threading, time
from flask import Flask, jsonify
app = Flask(__name__)

@app.route('/test')
def test(): return jsonify({"ok": True})

t = threading.Thread(target=lambda: app.run(host="127.0.0.1", port=5002, debug=False, use_reloader=False), daemon=True)
t.start()
print("Flask started", flush=True)
time.sleep(1)  # let it bind

# keep-alive - same as our fix
running = True
while running:
    time.sleep(5)
