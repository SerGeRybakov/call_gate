import multiprocessing
import sys
import threading

from datetime import timedelta

import pytest

import call_gate.gate

from call_gate import SlidingTimegate


# Функция для создания Manager с зарегистрированным классом
def get_manager():
    class MyManager(multiprocessing.Manager):
        pass

    MyManager.register("SlidingTimegate", SlidingTimegate)
    manager = MyManager()
    manager.start()
    return manager


@pytest.fixture(params=["fork", "spawn"])
def shared_gate(request):
    """Создает общий объект SlidingTimegate через multiprocessing.Manager"""
    method = request.param
    if method == "fork" and sys.platform == "win32":
        pytest.skip("Fork не поддерживается на gates")

    with get_manager() as manager:
        gate = call_gate.gate.SlidingTimegate(timedelta(seconds=10), timedelta(seconds=1))
        yield gate


# Функции-воркеры для тестов
def process_worker_inc(shared_gate, count):
    for _ in range(count):
        shared_gate.update(1)


def process_worker_threads(shared_gate, inc_count, thread_count):
    threads = []
    for _ in range(thread_count):
        t = threading.Thread(target=process_worker_inc, args=(shared_gate, inc_count))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()


@pytest.mark.parametrize("method", ["fork", "spawn"])
def test_multiprocessing(shared_gate, method):
    if method == "fork" and sys.platform == "win32":
        pytest.skip("Fork не поддерживается на gates")

    ctx = multiprocessing.get_context(method)
    processes = []
    inc_per_process = 1000
    process_count = 5
    for _ in range(process_count):
        p = ctx.Process(target=process_worker_inc, args=(shared_gate, inc_per_process))
        processes.append(p)
        p.start()
    for p in processes:
        p.join()

    expected = process_count * inc_per_process
    assert shared_gate.sum == expected, f"Expected sum {expected}, got {shared_gate.sum}"


@pytest.mark.parametrize("method", ["fork", "spawn"])
def test_multithreading_in_multiprocessing(shared_gate, method):
    if method == "fork" and sys.platform == "win32":
        pytest.skip("Fork не поддерживается на gates")

    ctx = multiprocessing.get_context(method)
    processes = []
    inc_per_thread = 500
    threads_per_process = 5
    process_count = 3
    for _ in range(process_count):
        p = ctx.Process(target=process_worker_threads, args=(shared_gate, inc_per_thread, threads_per_process))
        processes.append(p)
        p.start()
    for p in processes:
        p.join()

    expected = process_count * threads_per_process * inc_per_thread
    assert shared_gate.sum == expected, f"Expected sum {expected}, got {shared_gate.sum}"
