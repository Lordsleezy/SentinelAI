import threading, time, os
from flask import Flask, jsonify
from flask_socketio import SocketIO

app = Flask(__name__)
sio = SocketIO(app, cors_allowed_origins="*", async_mode="threading", logger=False, engineio_logger=False)

@app.route("/test")
def test(): return jsonify({"ok": True})

t = threading.Thread(target=lambda: sio.run(app, host="127.0.0.1", port=5002, debug=False, use_reloader=False, allow_unsafe_werkzeug=True), daemon=True)
t.start()
print("SocketIO thread started", flush=True)
time.sleep(1)

# keep-alive  
while True:
    time.sleep(5)
