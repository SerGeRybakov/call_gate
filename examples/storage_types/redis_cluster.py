from datetime import timedelta

from redis.cluster import ClusterNode, RedisCluster

from call_gate import CallGate, ThrottlingError


def main() -> None:
    client = RedisCluster(
        startup_nodes=[
            ClusterNode(host="127.0.0.1", port=7001),
            ClusterNode(host="127.0.0.1", port=7002),
            ClusterNode(host="127.0.0.1", port=7003),
        ],
        decode_responses=True,
    )
    client.ping()

    gate = CallGate(
        "redis_cluster",
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
