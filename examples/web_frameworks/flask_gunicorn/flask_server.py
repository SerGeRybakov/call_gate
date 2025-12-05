from datetime import timedelta

from flask import Flask, jsonify

from call_gate import CallGate, ThrottlingError


app = Flask(__name__)

gate = CallGate(
    "flask_api", timedelta(seconds=10), timedelta(milliseconds=100), gate_limit=100, frame_limit=2, storage="shared"
)


@app.route("/ping")
@gate(value=1, throw=False)
def ping():
    return jsonify({"ok": True, "sum": gate.sum})


@app.route("/limited")
def limited():
    with gate(value=2, throw=True):
        return jsonify({"sum": gate.sum, "data": gate.data})


@app.errorhandler(ThrottlingError)
def handle_throttling(exc):
    return jsonify({"error": str(exc)}), 429


if __name__ == "__main__":
    # For local debug. In production run with:
    # gunicorn -w 4 -b 0.0.0.0:5000 flask_server:app
    app.run(host="0.0.0.0", port=5000, debug=True)
