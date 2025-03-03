import multiprocessing

from concurrent.futures import ProcessPoolExecutor

import pytest

from call_gate import CallGate, GateStorageType
from tests.parameters import start_methods, storages


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


# ======================================================================
# Tests for updating through multiprocessing.Process
# ======================================================================


@pytest.mark.parametrize("start_method", start_methods)
@pytest.mark.parametrize("storage", storages)
@pytest.mark.parametrize(
    "num_processes, num_updates, update_value",
    [
        (4, 50, 1),
        (8, 25, 2),
    ],
)
def test_multiprocessing_updates(
    start_method: str, num_processes: int, num_updates: int, update_value: int, storage: str
):
    # Set the process start method
    multiprocessing.set_start_method(start_method, force=True)
    gate = CallGate("mp_gate", gate_size=60, frame_step=1, storage=storage)
    processes = []
    for _ in range(num_processes):
        p = multiprocessing.Process(target=process_worker, args=(gate, num_updates, update_value))
        processes.append(p)
        p.start()
    for p in processes:
        p.join()
    expected = num_processes * num_updates * update_value
    try:
        if storage == "simple" or storage == GateStorageType.simple:
            assert gate.sum != expected
        else:
            assert gate.sum == expected
    finally:
        gate.clear()


# ======================================================================
# Tests for context manager in multiprocessing
# ======================================================================


@pytest.mark.parametrize("start_method", start_methods)
@pytest.mark.parametrize("storage", storages)
@pytest.mark.parametrize(
    "num_processes, iterations, update_value",
    [
        (4, 10, 5),
        (8, 5, 3),
    ],
)
def test_context_manager_multiprocessing(
    start_method: str, num_processes: int, iterations: int, update_value: int, storage: str
):
    multiprocessing.set_start_method(start_method, force=True)
    gate = CallGate("mp_context_gate", gate_size=60, frame_step=1, storage=storage)
    processes = []
    for _ in range(num_processes):
        p = multiprocessing.Process(target=worker_context, args=(gate, iterations, update_value))
        processes.append(p)
        p.start()
    for p in processes:
        p.join()
    expected = num_processes * iterations * update_value
    try:
        if storage == "simple" or storage == GateStorageType.simple:
            assert gate.sum != expected
        else:
            assert gate.sum == expected
    finally:
        gate.clear()


# ======================================================================
# Tests for decorator in multiprocessing
# ======================================================================


@pytest.mark.parametrize("start_method", start_methods)
@pytest.mark.parametrize("storage", storages)
@pytest.mark.parametrize(
    "num_processes, iterations, update_value",
    [
        (4, 10, 2),
        (8, 5, 3),
    ],
)
def test_decorator_multiprocessing(
    start_method: str, num_processes: int, iterations: int, update_value: int, storage: str
):
    multiprocessing.set_start_method(start_method, force=True)
    gate = CallGate("mp_decorator_gate", gate_size=60, frame_step=1, storage=storage)
    processes = []
    for _ in range(num_processes):
        p = multiprocessing.Process(target=worker_decorator, args=(gate, iterations, update_value))
        processes.append(p)
        p.start()
    for p in processes:
        p.join()
    expected = num_processes * iterations * update_value
    try:
        if storage == "simple" or storage == GateStorageType.simple:
            assert gate.sum != expected
        else:
            assert gate.sum == expected
    finally:
        gate.clear()


# ======================================================================
# Tests for updating through ProcessPoolExecutor
# ======================================================================
@pytest.mark.parametrize("start_method", start_methods)
@pytest.mark.parametrize("storage", storages)
@pytest.mark.parametrize(
    "num_workers, num_updates, update_value",
    [
        (4, 50, 1),
        (8, 25, 2),
    ],
)
def test_process_pool_executor_updates(
    num_workers: int, num_updates: int, update_value: int, storage: str, start_method: str
):
    gate = CallGate("ppe_gate", gate_size=60, frame_step=1, storage=storage)
    multiprocessing.set_start_method(start_method, force=True)
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(process_worker, gate, num_updates, update_value) for _ in range(num_workers)]
        for future in futures:
            future.result()
    expected = num_workers * num_updates * update_value
    try:
        if storage == "simple" or storage == GateStorageType.simple:
            assert gate.sum != expected
        else:
            assert gate.sum == expected
    finally:
        gate.clear()


@pytest.mark.parametrize("start_method", start_methods)
@pytest.mark.parametrize("storage", storages)
@pytest.mark.parametrize(
    "num_workers, num_updates, update_value",
    [
        (4, 50, 1),
        (8, 25, 2),
    ],
)
def test_process_pool_executor_context(
    num_workers: int, num_updates: int, update_value: int, storage: str, start_method: str
):
    gate = CallGate("ppe_gate_context", gate_size=60, frame_step=1, storage=storage)
    multiprocessing.set_start_method(start_method, force=True)
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(worker_context, gate, num_updates, update_value) for _ in range(num_workers)]
        for future in futures:
            future.result()
    expected = num_workers * num_updates * update_value
    try:
        if storage == "simple" or storage == GateStorageType.simple:
            assert gate.sum != expected
        else:
            assert gate.sum == expected
    finally:
        gate.clear()


@pytest.mark.parametrize("start_method", start_methods)
@pytest.mark.parametrize("storage", storages)
@pytest.mark.parametrize(
    "num_workers, num_updates, update_value",
    [
        (4, 50, 1),
        (8, 25, 2),
    ],
)
def test_process_pool_executor_decorator(
    num_workers: int, num_updates: int, update_value: int, storage: str, start_method: str
):
    gate = CallGate("ppe_gate_decorator", gate_size=60, frame_step=1, storage=storage)
    multiprocessing.set_start_method(start_method, force=True)
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(worker_decorator, gate, num_updates, update_value) for _ in range(num_workers)]
        for future in futures:
            future.result()
    expected = num_workers * num_updates * update_value
    try:
        if storage == "simple" or storage == GateStorageType.simple:
            assert gate.sum != expected
        else:
            assert gate.sum == expected
    finally:
        gate.clear()


if __name__ == "__main__":
    pytest.main()
