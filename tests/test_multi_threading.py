import os
import threading

from concurrent.futures.thread import ThreadPoolExecutor

import pytest

from call_gate import CallGate
from tests.parameters import GITHUB_ACTIONS_REDIS_TIMEOUT, random_name, storages


def get_test_params() -> list[tuple[int, int, int]]:
    """Get test parameters based on the environment.

    ("num_threads", "updates_per_thread", "update_value")
    """
    if os.getenv("GITHUB_ACTIONS"):
        return [
            (2, 10, 2),
            (3, 20, 3),
            (5, 5, 4),
        ]
    return [
        (5, 200, 2),
        (10, 100, 3),
        (20, 50, 4),
    ]


@pytest.mark.timeout(GITHUB_ACTIONS_REDIS_TIMEOUT)
class TestCallGateInThreadsManual:
    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        ("num_threads", "updates_per_thread", "update_value"),
        get_test_params(),
    )
    def test_concurrent_updates(self, num_threads, updates_per_thread, update_value, storage):
        gate = CallGate(random_name(), gate_size=2, frame_step=1, storage=storage)

        def worker():
            for _ in range(updates_per_thread):
                gate.update(update_value)
            return 42

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected = num_threads * updates_per_thread * update_value
        try:
            assert gate.sum == expected
        finally:
            gate.clear()

    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        ("num_threads", "updates_per_thread", "update_value"),
        get_test_params(),
    )
    def test_decorated_function_concurrent(self, num_threads, updates_per_thread, update_value, storage):
        gate = CallGate(random_name(), gate_size=2, frame_step=1, storage=storage)

        @gate(update_value)
        def dummy_function():
            # Any function that returns a result
            return 42

        def worker():
            for _ in range(updates_per_thread):
                dummy_function()

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected = num_threads * updates_per_thread * update_value
        try:
            assert gate.sum == expected
        finally:
            gate.clear()

    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        ("num_threads", "updates_per_thread", "update_value"),
        get_test_params(),
    )
    def test_context_manager_concurrent(self, num_threads, updates_per_thread, update_value, storage):
        gate = CallGate(random_name(), gate_size=2, frame_step=1, storage=storage)

        def dummy_function(gate: "CallGate", update_value):
            # Any function that returns a result
            with gate(update_value):
                return 42

        def worker():
            for _ in range(updates_per_thread):
                dummy_function(gate, update_value)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected = num_threads * updates_per_thread * update_value
        try:
            assert gate.sum == expected
        finally:
            gate.clear()


@pytest.mark.timeout(GITHUB_ACTIONS_REDIS_TIMEOUT)
class TestCallGateInThreadsExecutor:
    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        ("num_threads", "updates_per_thread", "update_value"),
        get_test_params(),
    )
    def test_concurrent_updates(self, num_threads, updates_per_thread, update_value, storage):
        gate = CallGate(random_name(), gate_size=2, frame_step=1, storage=storage)

        def worker(*args, **kwargs):
            for _ in range(updates_per_thread):
                gate.update(update_value)
            return 42

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            executor.map(worker, range(num_threads))

        expected = num_threads * updates_per_thread * update_value
        try:
            assert gate.sum == expected
        finally:
            gate.clear()

    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        ("num_threads", "updates_per_thread", "update_value"),
        get_test_params(),
    )
    def test_decorated_function_concurrent(self, num_threads, updates_per_thread, update_value, storage):
        gate = CallGate(random_name(), gate_size=2, frame_step=1, storage=storage)

        @gate(update_value)
        def dummy_function():
            # Any function that returns a result
            return 42

        def worker(*args, **kwargs):
            for _ in range(updates_per_thread):
                dummy_function()

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            executor.map(worker, range(num_threads))

        expected = num_threads * updates_per_thread * update_value
        try:
            assert gate.sum == expected
        finally:
            gate.clear()

    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        ("num_threads", "updates_per_thread", "update_value"),
        get_test_params(),
    )
    def test_context_manager_concurrent(self, num_threads, updates_per_thread, update_value, storage):
        gate = CallGate(random_name(), gate_size=2, frame_step=1, storage=storage)

        def dummy_function(gate: "CallGate", update_value):
            # Any function that returns a result
            with gate(update_value):
                return 42

        def worker(*args, **kwargs):
            for _ in range(updates_per_thread):
                dummy_function(gate, update_value)

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            executor.map(worker, range(num_threads))

        expected = num_threads * updates_per_thread * update_value
        try:
            assert gate.sum == expected
        finally:
            gate.clear()


if __name__ == "__main__":
    pytest.main()
