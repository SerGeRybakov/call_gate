import multiprocessing
import os

from concurrent.futures import ProcessPoolExecutor

import pytest

from call_gate import CallGate, GateStorageType
from tests.parameters import GITHUB_ACTIONS_REDIS_TIMEOUT, random_name, start_methods, storages


def get_test_params() -> list[tuple[int, int, int]]:
    """Get test parameters based on the environment.

    ("num_processes", "num_updates", "update_value")
    """
    if os.getenv("GITHUB_ACTIONS"):
        return [
            (2, 20, 1),
            (3, 10, 2),
        ]
    return [
        (4, 50, 1),
        (8, 25, 2),
    ]


# ======================================================================
# Helper worker functions
# ======================================================================


def process_worker(gate: CallGate, num_updates: int, update_value: int) -> None:
    for _ in range(num_updates):
        gate.update(update_value)


def worker_context(gate: CallGate, iterations: int, update_value: int) -> None:
    for _ in range(iterations):
        with gate(update_value):
            pass


def worker_decorator(gate: CallGate, iterations: int, update_value: int) -> None:
    @gate(update_value)
    def dummy():
        pass

    for _ in range(iterations):
        dummy()


@pytest.mark.timeout(GITHUB_ACTIONS_REDIS_TIMEOUT)
class TestCallGateMultiprocessing:
    @pytest.mark.parametrize("start_method", start_methods)
    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        ("num_processes", "num_updates", "update_value"),
        get_test_params(),
    )
    def test_multiprocessing_updates(
        self, start_method: str, num_processes: int, num_updates: int, update_value: int, storage: str
    ):
        # Set the process start method
        multiprocessing.set_start_method(start_method, force=True)
        gate = CallGate(random_name(), gate_size=60, frame_step=1, storage=storage)
        processes = []
        for _ in range(num_processes):
            p = multiprocessing.Process(target=process_worker, args=(gate, num_updates, update_value))
            processes.append(p)
            p.start()
        for p in processes:
            p.join()
        expected = num_processes * num_updates * update_value
        try:
            if storage in ("simple", GateStorageType.simple):
                assert gate.sum != expected
            else:
                assert gate.sum == expected
        finally:
            gate.clear()

    @pytest.mark.parametrize("start_method", start_methods)
    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        ("num_processes", "iterations", "update_value"),
        get_test_params(),
    )
    def test_context_manager_multiprocessing(
        self, start_method: str, num_processes: int, iterations: int, update_value: int, storage: str
    ):
        multiprocessing.set_start_method(start_method, force=True)
        gate = CallGate(random_name(), gate_size=60, frame_step=1, storage=storage)
        processes = []
        for _ in range(num_processes):
            p = multiprocessing.Process(target=worker_context, args=(gate, iterations, update_value))
            processes.append(p)
            p.start()
        for p in processes:
            p.join()
        expected = num_processes * iterations * update_value
        try:
            if storage in ("simple", GateStorageType.simple):
                assert gate.sum != expected
            else:
                assert gate.sum == expected
        finally:
            gate.clear()

    @pytest.mark.parametrize("start_method", start_methods)
    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        ("num_processes", "iterations", "update_value"),
        get_test_params(),
    )
    def test_decorator_multiprocessing(
        self, start_method: str, num_processes: int, iterations: int, update_value: int, storage: str
    ):
        multiprocessing.set_start_method(start_method, force=True)
        gate = CallGate(random_name(), gate_size=60, frame_step=1, storage=storage)
        processes = []
        for _ in range(num_processes):
            p = multiprocessing.Process(target=worker_decorator, args=(gate, iterations, update_value))
            processes.append(p)
            p.start()
        for p in processes:
            p.join()
        expected = num_processes * iterations * update_value
        try:
            if storage in ("simple", GateStorageType.simple):
                assert gate.sum != expected
            else:
                assert gate.sum == expected
        finally:
            gate.clear()


@pytest.mark.timeout(GITHUB_ACTIONS_REDIS_TIMEOUT)
class TestCallGateMultiprocessingExecutor:
    @pytest.mark.parametrize("start_method", start_methods)
    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        ("num_workers", "num_updates", "update_value"),
        get_test_params(),
    )
    def test_process_pool_executor_updates(
        self, num_workers: int, num_updates: int, update_value: int, storage: str, start_method: str
    ):
        gate = CallGate(random_name(), gate_size=60, frame_step=1, storage=storage)
        multiprocessing.set_start_method(start_method, force=True)
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(process_worker, gate, num_updates, update_value) for _ in range(num_workers)]
            for future in futures:
                future.result()
        expected = num_workers * num_updates * update_value
        try:
            if storage in ("simple", GateStorageType.simple):
                assert gate.sum != expected
            else:
                assert gate.sum == expected
        finally:
            gate.clear()

    @pytest.mark.parametrize("start_method", start_methods)
    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        ("num_workers", "num_updates", "update_value"),
        get_test_params(),
    )
    def test_process_pool_executor_context(
        self, num_workers: int, num_updates: int, update_value: int, storage: str, start_method: str
    ):
        gate = CallGate(random_name(), gate_size=60, frame_step=1, storage=storage)
        multiprocessing.set_start_method(start_method, force=True)
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(worker_context, gate, num_updates, update_value) for _ in range(num_workers)]
            for future in futures:
                future.result()
        expected = num_workers * num_updates * update_value
        try:
            if storage in ("simple", GateStorageType.simple):
                assert gate.sum != expected
            else:
                assert gate.sum == expected
        finally:
            gate.clear()

    @pytest.mark.parametrize("start_method", start_methods)
    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        ("num_workers", "num_updates", "update_value"),
        get_test_params(),
    )
    def test_process_pool_executor_decorator(
        self, num_workers: int, num_updates: int, update_value: int, storage: str, start_method: str
    ):
        gate = CallGate(random_name(), gate_size=60, frame_step=1, storage=storage)
        multiprocessing.set_start_method(start_method, force=True)
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(worker_decorator, gate, num_updates, update_value) for _ in range(num_workers)]
            for future in futures:
                future.result()
        expected = num_workers * num_updates * update_value
        try:
            if storage in ("simple", GateStorageType.simple):
                assert gate.sum != expected
            else:
                assert gate.sum == expected
        finally:
            gate.clear()


if __name__ == "__main__":
    pytest.main()
