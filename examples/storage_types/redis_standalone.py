from datetime import timedelta

import redis

from call_gate import CallGate, ThrottlingError


def main() -> None:
    client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    client.ping()

    gate = CallGate(
        "redis_standalone",
        timedelta(seconds=1),
        timedelta(milliseconds=500),
        gate_limit=3,
        frame_limit=2,
        storage="redis",
        redis_client=client,
    )
    try:
        gate.update(2)  # reach frame limit
        gate.update(throw=False)  # exceed frame limit, wait and increment 1
        gate.update(throw=True)  # exceed gate limit, raise
    except ThrottlingError as exc:
        print(exc)
    print(gate.state)


if __name__ == "__main__":
    main()
