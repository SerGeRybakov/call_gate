from redis.sentinel import Sentinel

from call_gate import CallGate


def main() -> None:
    sentinel = Sentinel([("localhost", 26379)], decode_responses=True)
    try:
        # Anti-pattern: Sentinel must not be passed directly
        CallGate("bad_sentinel", 10, 1, storage="redis", redis_client=sentinel)
    except Exception as exc:
        print(f"Expected error: {exc}")


if __name__ == "__main__":
    main()
