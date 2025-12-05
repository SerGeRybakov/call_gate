from datetime import timedelta

from redis import Redis, Sentinel

from call_gate import CallGate, ThrottlingError


def main() -> None:
    sentinel: Sentinel = Sentinel(
        [("localhost", 26379), ("localhost", 26380), ("localhost", 26381)],
        socket_timeout=1.0,
        decode_responses=True,
    )
    client: Redis = sentinel.master_for("mymaster", decode_responses=True, db=15)
    client.ping()

    gate = CallGate(
        "redis_sentinel",
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
