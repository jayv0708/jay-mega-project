from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.route("/")
def health_check():
    return jsonify({"status": "ok", "service": "log-ui"})

@app.route("/status")
def status():
    return jsonify({"status": "running", "log_targets": []})

if __name__ == "__main__":
    host = os.environ.get("LOG_UI_HOST", "0.0.0.0")
    port = int(os.environ.get("LOG_UI_PORT", 8080))
    app.run(host=host, port=port)
