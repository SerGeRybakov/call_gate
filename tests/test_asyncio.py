import asyncio

from datetime import timedelta

import pytest

from call_gate import CallGate, FrameLimitError, GateLimitError
from tests.parameters import (
    GITHUB_ACTIONS_REDIS_TIMEOUT,
    create_call_gate,
    random_name,
    storages,
    xfail_marker,
)


LOCK_MODEL_STORAGES = ["simple", pytest.param("redis", marks=xfail_marker)]


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
@pytest.mark.timeout(GITHUB_ACTIONS_REDIS_TIMEOUT)
class TestCallGateAsyncioHelpers:
    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize("update_value", [1, 5, 10])
    async def test_async_worker(self, update_value, storage):
        gate = create_call_gate(
            random_name(), timedelta(seconds=1), timedelta(milliseconds=100), frame_limit=10, storage=storage
        )
        await worker(gate, update_value)
        try:
            assert gate.sum == update_value
            assert gate.current_frame.value == update_value
        finally:
            await gate.clear()

    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        ("iterations", "update_value"),
        [
            (1, 3),
            (5, 10),
            (10, 5),
        ],
    )
    async def test_async_worker_context(self, iterations, update_value, storage):
        gate = create_call_gate(
            random_name(),
            timedelta(seconds=1),
            timedelta(milliseconds=100),
            frame_limit=10,
            storage=storage,
        )
        await worker_context(gate, iterations, update_value)
        expected_sum = iterations * update_value
        try:
            assert gate.sum == expected_sum
        finally:
            await gate.clear()

    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        ("iterations", "update_value"),
        [
            (1, 3),
            (5, 10),
            (10, 5),
        ],
    )
    async def test_async_worker_decorator(self, iterations, update_value, storage):
        gate = create_call_gate(
            random_name(),
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


@pytest.mark.asyncio
@pytest.mark.timeout(GITHUB_ACTIONS_REDIS_TIMEOUT)
class TestCallGateAsyncio:
    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize("update_value", [1, 5, 10])
    async def test_async(self, update_value, storage):
        gate = create_call_gate(
            random_name(), timedelta(seconds=1), timedelta(milliseconds=100), frame_limit=10, storage=storage
        )
        await gate.update(update_value)
        try:
            assert gate.sum == update_value
            assert gate.current_frame.value == update_value
        finally:
            await gate.clear()

    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        ("iterations", "update_value"),
        [
            (1, 3),
            (5, 10),
            (10, 5),
        ],
    )
    async def test_async_context(self, iterations, update_value, storage):
        gate = create_call_gate(
            random_name(), timedelta(seconds=1), timedelta(milliseconds=100), frame_limit=10, storage=storage
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
        ("iterations", "update_value"),
        [
            (1, 3),
            (5, 10),
            (10, 5),
        ],
    )
    async def test_async_decorator(self, iterations, update_value, storage):
        gate = create_call_gate(
            random_name(),
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
        gate = create_call_gate(
            random_name(),
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
        gate = create_call_gate(
            random_name(),
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

    @pytest.mark.parametrize("storage", LOCK_MODEL_STORAGES)
    async def test_check_limits_stale_window_async(self, storage):
        gate = create_call_gate(
            random_name(),
            timedelta(milliseconds=150),
            timedelta(milliseconds=50),
            gate_limit=1,
            frame_limit=1,
            storage=storage,
        )

        await gate.update()
        stale_dt = gate._current_step() - gate.frame_step * gate.frames
        gate._current_dt = stale_dt
        gate._data.set_timestamp(stale_dt)

        try:
            await gate.check_limits()

            assert gate.sum == 0
            assert gate.data == [0] * gate.frames
            assert gate.current_frame.value == 0
            assert gate.current_dt is None
            assert gate._data.get_timestamp() is None
        finally:
            await gate.clear()


if __name__ == "__main__":
    pytest.main()
