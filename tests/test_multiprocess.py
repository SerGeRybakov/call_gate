import multiprocessing
import sys
import threading

from datetime import timedelta

import pytest

import sliding_window.window

from sliding_window import SlidingTimeWindow


# Функция для создания Manager с зарегистрированным классом
def get_manager():
    class MyManager(multiprocessing.Manager):
        pass

    MyManager.register("SlidingTimeWindow", SlidingTimeWindow)
    manager = MyManager()
    manager.start()
    return manager


@pytest.fixture(params=["fork", "spawn"])
def shared_window(request):
    """Создает общий объект SlidingTimeWindow через multiprocessing.Manager"""
    method = request.param
    if method == "fork" and sys.platform == "win32":
        pytest.skip("Fork не поддерживается на Windows")

    with get_manager() as manager:
        window = sliding_window.window.SlidingTimeWindow(timedelta(seconds=10), timedelta(seconds=1))
        yield window


# Функции-воркеры для тестов
def process_worker_inc(shared_window, count):
    for _ in range(count):
        shared_window.inc(1)


def process_worker_threads(shared_window, inc_count, thread_count):
    threads = []
    for _ in range(thread_count):
        t = threading.Thread(target=process_worker_inc, args=(shared_window, inc_count))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()


@pytest.mark.parametrize("method", ["fork", "spawn"])
def test_multiprocessing(shared_window, method):
    if method == "fork" and sys.platform == "win32":
        pytest.skip("Fork не поддерживается на Windows")

    ctx = multiprocessing.get_context(method)
    processes = []
    inc_per_process = 1000
    process_count = 5
    for _ in range(process_count):
        p = ctx.Process(target=process_worker_inc, args=(shared_window, inc_per_process))
        processes.append(p)
        p.start()
    for p in processes:
        p.join()

    expected = process_count * inc_per_process
    assert shared_window.sum == expected, f"Expected sum {expected}, got {shared_window.sum}"


@pytest.mark.parametrize("method", ["fork", "spawn"])
def test_multithreading_in_multiprocessing(shared_window, method):
    if method == "fork" and sys.platform == "win32":
        pytest.skip("Fork не поддерживается на Windows")

    ctx = multiprocessing.get_context(method)
    processes = []
    inc_per_thread = 500
    threads_per_process = 5
    process_count = 3
    for _ in range(process_count):
        p = ctx.Process(target=process_worker_threads, args=(shared_window, inc_per_thread, threads_per_process))
        processes.append(p)
        p.start()
    for p in processes:
        p.join()

    expected = process_count * threads_per_process * inc_per_thread
    assert shared_window.sum == expected, f"Expected sum {expected}, got {shared_window.sum}"
