import asyncio

from datetime import timedelta

from call_gate import CallGate, ThrottlingError


gate = CallGate(
    "decorator",
    timedelta(seconds=1),
    timedelta(milliseconds=500),
    gate_limit=3,
    frame_limit=2,
)


@gate(value=1, throw=True)
def sync_example() -> str:
    return "sync"


@gate(value=2, throw=True)
async def async_example() -> str:
    return "async"


if __name__ == "__main__":
    try:
        print(sync_example())
        print(asyncio.run(async_example()))  # exceeds limit
        print(sync_example())  # never runs
    except ThrottlingError as exc:
        print(exc)
    print(gate.state)
