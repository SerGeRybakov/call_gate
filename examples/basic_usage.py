import asyncio

from datetime import timedelta
from random import randint

from call_gate import CallGate, ThrottlingError


def sync_func(gate: CallGate):
    try:
        gate.update()  # update 1
        gate.update(2)  # exceed frame limit, wait and increment 2
        gate.update(value=randint(1, 2), throw=True)  # exceed frame limit, raise
    except ThrottlingError as exc:
        print(exc)


async def async_func(gate: CallGate) -> None:
    try:
        await gate.update()  # update 1
        await gate.update(2)  # exceed frame limit, wait and increment 2
        await gate.update(value=randint(1, 2), throw=True)  # exceed frame limit, raise
    except ThrottlingError as exc:
        print(exc)


if __name__ == "__main__":
    my_gate = CallGate(
        "basic",
        timedelta(seconds=1),
        timedelta(milliseconds=500),
        gate_limit=3,
        frame_limit=2,
    )
    sync_func(my_gate)
    asyncio.run(async_func(my_gate))
    print(my_gate.state)
    assert my_gate.sum <= my_gate.gate_limit
