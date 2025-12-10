import asyncio

from datetime import timedelta

from call_gate import CallGate, ThrottlingError


def sync_example(gate: CallGate) -> None:
    with gate(value=2, throw=False):
        pass
    try:
        with gate(value=1, throw=True):  # exceed frame_limit, raise
            pass
    except ThrottlingError as exc:
        print("sync", exc)


async def async_example(gate: CallGate) -> None:
    async with gate(value=1, throw=False):  # exceed frame limit, wait and increment 1
        pass
    try:
        async with gate(value=2, throw=True):  # exceed frame limit, raise
            pass
    except ThrottlingError as exc:
        print("async", exc)


if __name__ == "__main__":
    my_gate = CallGate(
        "ctx",
        timedelta(seconds=1),
        timedelta(milliseconds=500),
        gate_limit=3,
        frame_limit=2,
    )
    try:
        sync_example(my_gate)
        asyncio.run(async_example(my_gate))
    finally:
        print(my_gate.state)
