import atexit

from datetime import timedelta

from flask import Flask, abort, jsonify

from call_gate import GateStorageType
from tests.parameters import create_call_gate


app = Flask(__name__)
gate = create_call_gate(
    "api_gate",
    timedelta(seconds=2),
    timedelta(milliseconds=100),
    gate_limit=10,
    frame_limit=4,
    storage=GateStorageType.redis,
)
gate.clear()


@app.route("/")
def root():
    try:
        gate.update(throw=True)
        return jsonify(message="Hello, World!")
    except Exception:
        abort(429, description="Rate limit exceeded")


@atexit.register
def cleanup_gate():
    gate.clear()
