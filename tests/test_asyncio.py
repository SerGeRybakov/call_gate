import asyncio

from datetime import timedelta

import pytest

from call_gate import CallGate, ThrottlingError, GateLimitError, FrameLimitError
from tests.parameters import storages


# ======================================================================
# Helper worker functions
# ======================================================================


async def worker(gate: CallGate, update_value: int) -> None:
    await gate.update(update_value)


async def worker_context(gate: CallGate, iterations: int, update_value: int) -> None:
    async def dummy(value):
        async with gate(value):
            pass

    await asyncio.gather(*[dummy(update_value) for _ in range(iterations)])


async def worker_decorator(gate: CallGate, iterations: int, update_value: int) -> None:
    @gate(update_value)
    async def dummy():
        pass

    await asyncio.gather(*[dummy() for _ in range(iterations)])

@pytest.mark.asyncio
class TestCallGateAsyncioHelpers:
    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize("update_value", [1, 5, 10])
    async def test_async_worker(self, update_value, storage):
        gate = CallGate(
            "async_worker_gate", timedelta(seconds=1), timedelta(milliseconds=100), frame_limit=10, storage=storage
        )
        await worker(gate, update_value)
        try:
            assert gate.sum == update_value
            assert gate.current_frame.value == update_value
        finally:
            await gate.clear()


    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        "iterations, update_value",
        [
            (1, 3),
            (5, 10),
            (10, 5),
        ],
    )
    async def test_async_worker_context(self, iterations, update_value, storage):
        gate = CallGate(
            "async_worker_gate_context", timedelta(seconds=1), timedelta(milliseconds=100), frame_limit=10, storage=storage
        )
        await worker_context(gate, iterations, update_value)
        expected_sum = iterations * update_value
        try:
            assert gate.sum == expected_sum
        finally:
            await gate.clear()

    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        "iterations, update_value",
        [
            (1, 3),
            (5, 10),
            (10, 5),
        ],
    )
    async def test_async_worker_decorator(self, iterations, update_value, storage):
        gate = CallGate(
            "async_worker_gate_decorator",
            timedelta(seconds=1),
            timedelta(milliseconds=100),
            frame_limit=10,
            storage=storage,
        )
        await worker_decorator(gate, iterations, update_value)
        expected_sum = iterations * update_value
        try:
            assert gate.sum == expected_sum
        finally:
            await gate.clear()


@pytest.mark.asyncio()
class TestCallGateAsyncio:

    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize("update_value", [1, 5, 10])
    async def test_async(self, update_value, storage):
        gate = CallGate(
            "async_gate", timedelta(seconds=1), timedelta(milliseconds=100), frame_limit=10, storage=storage
        )
        await gate.update(update_value)
        try:
            assert gate.sum == update_value
            assert gate.current_frame.value == update_value
        finally:
            await gate.clear()


    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        "iterations, update_value",
        [
            (1, 3),
            (5, 10),
            (10, 5),
        ],
    )
    async def test_async_context(self, iterations, update_value, storage):
        gate = CallGate(
            "async_gate_context", timedelta(seconds=1), timedelta(milliseconds=100), frame_limit=10, storage=storage
        )

        async def dummy(value):
            await gate.update(value)

        await asyncio.gather(*[dummy(update_value) for _ in range(iterations)])

        expected_sum = iterations * update_value
        try:
            assert gate.sum == expected_sum
        finally:
            await gate.clear()



    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        "iterations, update_value",
        [
            (1, 3),
            (5, 10),
            (10, 5),
        ],
    )
    async def test_async_decorator(self, iterations, update_value, storage):
        gate = CallGate(
            "async_gate_decorator",
            timedelta(seconds=1),
            timedelta(milliseconds=100),
            frame_limit=10,
            storage=storage,
        )

        @gate(value=update_value)
        async def dummy():
            pass

        await asyncio.gather(*[dummy() for _ in range(iterations)])

        expected_sum = iterations * update_value
        try:
            assert gate.sum == expected_sum
        finally:
            await gate.clear()


    @pytest.mark.parametrize("storage", storages)
    async def test_check_limits_gate_async(self, storage):
        gate = CallGate(
            "check_limits",
            timedelta(seconds=1),
            timedelta(milliseconds=100),
            gate_limit=100,
            frame_limit=10,
            storage=storage,
        )

        while gate.sum < gate.gate_limit:
            await gate.update()

        try:
            with pytest.raises(GateLimitError):
                await gate.check_limits()
        finally:
            await gate.clear()

    @pytest.mark.parametrize("storage", storages)
    async def test_check_limits_frame_async(self, storage):
        gate = CallGate(
            "check_limits",
            timedelta(seconds=1),
            timedelta(milliseconds=100),
            gate_limit=100,
            frame_limit=10,
            storage=storage,
        )

        while gate.current_frame.value < gate.frame_limit:
            await gate.update()

        try:
            with pytest.raises(FrameLimitError):
                await gate.check_limits()
        finally:
            await gate.clear()


if __name__ == "__main__":
    pytest.main()
