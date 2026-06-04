"""
Tests for distributed refresh / stale _current_dt bug (Redis and shared).

Reproduces scenario where writers call update() and monitor calls
check_limits() only. Without syncing _current_dt from storage before slide,
monitor double-slides and loses sum.
"""

import multiprocessing
import threading
import time

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from call_gate import CallGate, GateStorageType
from tests.parameters import (
    GITHUB_ACTIONS_REDIS_TIMEOUT,
    create_call_gate,
    create_redis_client,
    random_name,
)


def _fake_current_step_factory(base: datetime, frame_step: timedelta):
    """Return (advance_fn, patch_target) for deterministic frame stepping."""
    state = {"now": base}

    def advance(seconds: float) -> None:
        state["now"] += timedelta(seconds=seconds)

    def fake_current_step(gate_self):
        t = state["now"]
        remainder = t.timestamp() % gate_self._frame_step.total_seconds()
        return t - timedelta(seconds=remainder)

    return advance, fake_current_step


@pytest.mark.timeout(GITHUB_ACTIONS_REDIS_TIMEOUT)
class TestRedisDistributedRefresh:
    """Stale _current_dt causes spurious slide and sum loss."""

    def test_monitor_check_limits_double_slide_repro(self):
        """Monitor with stale _current_dt re-slides after writers."""
        gate_name = random_name()
        frame_step = timedelta(seconds=1)
        base = datetime(2026, 6, 1, 12, 0, 0)
        advance, fake_step = _fake_current_step_factory(base, frame_step)

        redis_client = create_redis_client()
        gate_writer = CallGate(
            gate_name,
            gate_size=timedelta(seconds=10),
            frame_step=frame_step,
            storage=GateStorageType.redis,
            redis_client=redis_client,
        )
        gate_monitor = CallGate(
            gate_name,
            gate_size=timedelta(seconds=10),
            frame_step=frame_step,
            storage=GateStorageType.redis,
            redis_client=redis_client,
        )

        try:
            with patch.object(CallGate, "_current_step", fake_step):
                for _ in range(5):
                    gate_writer.update(1)

                gate_monitor.check_limits()

                advance(5)
                for _ in range(5):
                    gate_writer.update(1)

                gate_monitor.check_limits()

            assert gate_writer.sum == 10
            assert gate_monitor.sum == 10
            assert sum(gate_writer.data) == gate_writer.sum
        finally:
            gate_writer.clear()

    def test_sum_invariant_after_updates_and_monitor(self):
        """LRANGE sum must match :sum after writers + monitor activity."""
        gate_name = random_name()
        redis_client = create_redis_client()
        gate_writer = CallGate(
            gate_name,
            gate_size=timedelta(seconds=15),
            frame_step=timedelta(seconds=1),
            storage=GateStorageType.redis,
            redis_client=redis_client,
        )
        gate_monitor = CallGate(
            gate_name,
            gate_size=timedelta(seconds=15),
            frame_step=timedelta(seconds=1),
            storage=GateStorageType.redis,
            redis_client=redis_client,
        )
        stop = threading.Event()
        total_updates = 30

        def monitor_loop():
            while not stop.is_set():
                try:
                    gate_monitor.check_limits()
                except Exception:
                    pass
                time.sleep(0.05)

        try:
            monitor = threading.Thread(target=monitor_loop)
            monitor.start()

            for _ in range(total_updates):
                gate_writer.update(1)
                time.sleep(0.05)

            stop.set()
            monitor.join(timeout=5)

            assert gate_writer.sum == total_updates
            assert sum(gate_writer.data) == gate_writer.sum
        finally:
            stop.set()
            gate_writer.clear()


def _writer_worker(gate_name: str, num_updates: int, sleep_s: float) -> None:
    redis_client = create_redis_client()
    gate = CallGate(
        gate_name,
        gate_size=timedelta(seconds=20),
        frame_step=timedelta(seconds=1),
        storage=GateStorageType.redis,
        redis_client=redis_client,
    )
    for _ in range(num_updates):
        gate.update(1)
        time.sleep(sleep_s)


def _monitor_worker(gate_name: str, duration_s: float) -> None:
    redis_client = create_redis_client()
    gate = CallGate(
        gate_name,
        gate_size=timedelta(seconds=20),
        frame_step=timedelta(seconds=1),
        storage=GateStorageType.redis,
        redis_client=redis_client,
    )
    deadline = time.monotonic() + duration_s
    while time.monotonic() < deadline:
        try:
            gate.check_limits()
        except Exception:
            pass
        time.sleep(0.1)


@pytest.mark.timeout(GITHUB_ACTIONS_REDIS_TIMEOUT)
class TestRedisDistributedRefreshMultiprocess:
    """Separate CallGate per process; monitor without update."""

    def test_multiprocess_writers_and_monitor(self):
        gate_name = random_name()
        num_writers = 3
        updates_per_writer = 10
        sleep_s = 0.2
        expected = num_writers * updates_per_writer

        redis_client = create_redis_client()
        seed = CallGate(
            gate_name,
            gate_size=timedelta(seconds=20),
            frame_step=timedelta(seconds=1),
            storage=GateStorageType.redis,
            redis_client=redis_client,
        )
        seed.clear()

        duration = num_writers * updates_per_writer * sleep_s + 2
        processes = []

        try:
            multiprocessing.set_start_method("fork", force=True)

            for _ in range(num_writers):
                p = multiprocessing.Process(
                    target=_writer_worker,
                    args=(gate_name, updates_per_writer, sleep_s),
                )
                processes.append(p)
                p.start()

            monitor = multiprocessing.Process(
                target=_monitor_worker,
                args=(gate_name, duration),
            )
            monitor.start()

            for p in processes:
                p.join(timeout=60)
                assert p.exitcode == 0

            monitor.join(timeout=10)

            verifier = CallGate(
                gate_name,
                gate_size=timedelta(seconds=20),
                frame_step=timedelta(seconds=1),
                storage=GateStorageType.redis,
                redis_client=create_redis_client(),
            )
            assert verifier.sum == expected
            assert sum(verifier.data) == verifier.sum
        finally:
            for p in processes:
                if p.is_alive():
                    p.terminate()
            CallGate(
                gate_name,
                gate_size=timedelta(seconds=20),
                frame_step=timedelta(seconds=1),
                storage=GateStorageType.redis,
                redis_client=create_redis_client(),
            ).clear()


@pytest.mark.timeout(GITHUB_ACTIONS_REDIS_TIMEOUT)
class TestSharedDistributedRefresh:
    """Shared storage: stale local _current_dt vs shared timestamp."""

    def test_monitor_stale_current_dt_syncs_from_shared_timestamp(self):
        """Stale _current_dt is corrected from shared timestamp before slide."""
        frame_step = timedelta(seconds=1)
        base = datetime(2026, 6, 1, 12, 0, 0)
        advance, fake_step = _fake_current_step_factory(base, frame_step)

        gate = create_call_gate(
            random_name(),
            gate_size=timedelta(seconds=10),
            frame_step=frame_step,
            storage=GateStorageType.shared,
        )

        try:
            with patch.object(CallGate, "_current_step", fake_step):
                for _ in range(5):
                    gate.update(1)

                advance(5)
                for _ in range(5):
                    gate.update(1)

                gate._current_dt = base

                gate.check_limits()

            assert gate.sum == 10
            assert sum(gate.data) == gate.sum
        finally:
            gate.clear()


def _shared_writer_worker(gate: CallGate, num_updates: int, sleep_s: float) -> None:
    for _ in range(num_updates):
        gate.update(1)
        time.sleep(sleep_s)


def _shared_monitor_worker(gate: CallGate, duration_s: float) -> None:
    deadline = time.monotonic() + duration_s
    while time.monotonic() < deadline:
        try:
            gate.check_limits()
        except Exception:
            pass
        time.sleep(0.1)


@pytest.mark.timeout(GITHUB_ACTIONS_REDIS_TIMEOUT)
class TestSharedDistributedRefreshMultiprocess:
    """Fork workers share one gate object; monitor without update."""

    def test_multiprocess_writers_and_monitor(self):
        num_writers = 3
        updates_per_writer = 10
        sleep_s = 0.2
        expected = num_writers * updates_per_writer

        gate = create_call_gate(
            random_name(),
            gate_size=timedelta(seconds=20),
            frame_step=timedelta(seconds=1),
            storage=GateStorageType.shared,
        )
        gate.clear()

        duration = num_writers * updates_per_writer * sleep_s + 2
        processes = []

        try:
            multiprocessing.set_start_method("fork", force=True)

            for _ in range(num_writers):
                p = multiprocessing.Process(
                    target=_shared_writer_worker,
                    args=(gate, updates_per_writer, sleep_s),
                )
                processes.append(p)
                p.start()

            monitor = multiprocessing.Process(
                target=_shared_monitor_worker,
                args=(gate, duration),
            )
            monitor.start()

            for p in processes:
                p.join(timeout=60)
                assert p.exitcode == 0

            monitor.join(timeout=10)

            assert gate.sum == expected
            assert sum(gate.data) == gate.sum
        finally:
            for p in processes:
                if p.is_alive():
                    p.terminate()
            gate.clear()


@pytest.mark.timeout(GITHUB_ACTIONS_REDIS_TIMEOUT)
class TestTimestampSyncBehavior:
    def test_sync_skips_when_storage_has_no_timestamp(self):
        redis_client = create_redis_client()
        gate_name = random_name()
        gate = CallGate(
            gate_name,
            gate_size=timedelta(seconds=10),
            frame_step=timedelta(seconds=1),
            storage=GateStorageType.redis,
            redis_client=redis_client,
        )
        try:
            local_dt = datetime(2026, 6, 1, 12, 0, 0)
            gate._current_dt = local_dt
            gate._data.clear_timestamp()
            gate._sync_current_dt_from_storage()
            assert gate._current_dt == local_dt
        finally:
            gate.clear()

    def test_sync_adopts_storage_timestamp_when_local_cursor_missing(self):
        redis_client = create_redis_client()
        gate_name = random_name()
        writer = CallGate(
            gate_name,
            gate_size=timedelta(seconds=10),
            frame_step=timedelta(seconds=1),
            storage=GateStorageType.redis,
            redis_client=redis_client,
        )
        reader = CallGate(
            gate_name,
            gate_size=timedelta(seconds=10),
            frame_step=timedelta(seconds=1),
            storage=GateStorageType.redis,
            redis_client=redis_client,
        )
        try:
            writer.update(1)
            stored = writer._data.get_timestamp()
            assert stored is not None
            reader._current_dt = None
            reader._sync_current_dt_from_storage()
            assert reader._current_dt == reader._align_to_frame_step(stored)
        finally:
            writer.clear()
