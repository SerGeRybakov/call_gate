import atexit

from datetime import timedelta

from flask import Flask, abort, jsonify

from call_gate import GateStorageType
from tests.parameters import create_call_gate


app = Flask(__name__)
# Use fixed gate name so all workers share the same distributed gate
gate_name = "wsgi_shared_gate"
gate = create_call_gate(
    gate_name,
    timedelta(seconds=5),  # Longer window
    timedelta(milliseconds=500),  # Larger frames
    gate_limit=8,  # Lower gate limit
    frame_limit=2,  # Lower frame limit
    storage=GateStorageType.redis,
)


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
