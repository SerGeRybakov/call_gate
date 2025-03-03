import threading
from concurrent.futures.thread import ThreadPoolExecutor

import pytest

from call_gate import CallGate
from tests.parameters import storages


class TestCallGateInThreadsManual:
    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        ("num_threads", "updates_per_thread", "update_value"),
        [
            (10, 100, 2),  # 10 threads with 100 updates each, each update +2
            (20, 50, 3),  # 20 threads with 50 updates each, each update +3
            (5, 200, 4),  # 5 threads with 200 updates each, each update +3
        ],
    )
    def test_concurrent_updates(self, num_threads, updates_per_thread, update_value, storage):
        gate = CallGate("tp_gate", gate_size=2, frame_step=1, storage=storage)

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
        [
            (10, 100, 2),  # 10 threads with 100 updates each, each update +2
            (20, 50, 3),  # 20 threads with 50 updates each, each update +3
            (5, 200, 4),  # 5 threads with 200 updates each, each update +3
        ],
    )
    def test_decorated_function_concurrent(
        self, num_threads, updates_per_thread, update_value, storage
    ):
        gate = CallGate("tp_gate_decorated", gate_size=2, frame_step=1, storage=storage)

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
        [
            (10, 100, 2),  # 10 threads with 100 updates each, each update +2
            (20, 50, 3),  # 20 threads with 50 updates each, each update +3
            (5, 200, 4),  # 5 threads with 200 updates each, each update +3
        ],
    )
    def test_context_manager_concurrent(self, num_threads, updates_per_thread, update_value, storage):
        gate = CallGate("tp_gate_context", gate_size=2, frame_step=1, storage=storage)

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

class TestCallGateInThreadsExecutor:
    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        ("num_threads", "updates_per_thread", "update_value"),
        [
            (10, 100, 2),  # 10 threads with 100 updates each, each update +2
            (20, 50, 3),  # 20 threads with 50 updates each, each update +3
            (5, 200, 4),  # 5 threads with 200 updates each, each update +3
        ],
    )
    def test_concurrent_updates(self, num_threads, updates_per_thread, update_value, storage):
        gate = CallGate("tpe_gate", gate_size=2, frame_step=1, storage=storage)

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
        [
            (10, 100, 2),  # 10 threads with 100 updates each, each update +2
            (20, 50, 3),  # 20 threads with 50 updates each, each update +3
            (5, 200, 4),  # 5 threads with 200 updates each, each update +3
        ],
    )
    def test_decorated_function_concurrent(
        self, num_threads, updates_per_thread, update_value, storage
    ):
        gate = CallGate("tpe_gate_decorator", gate_size=2, frame_step=1, storage=storage)

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
        [
            (10, 100, 2),  # 10 threads with 100 updates each, each update +2
            (20, 50, 3),  # 20 threads with 50 updates each, each update +3
            (5, 200, 4),  # 5 threads with 200 updates each, each update +3
        ],
    )
    def test_context_manager_concurrent(self, num_threads, updates_per_thread, update_value, storage):
        gate = CallGate("tpe_gate_context", gate_size=2, frame_step=1, storage=storage)

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
