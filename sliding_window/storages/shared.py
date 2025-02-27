import fcntl
import warnings
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
from typing import List, Optional

import numpy as np
from numpy.typing import NDArray

from sliding_window import FrameLimitError, WindowLimitError
from sliding_window.base.base_storage import BaseWindowStorage


class GlobalLock:
    """Глобальный лок с файловой блокировкой для процессов."""

    def __init__(self, name: str):
        self.lockfile = Path(f".{name}.lock")
        self.fd = self.lockfile.open(mode="w")

    def acquire(self):
        fcntl.flock(self.fd, fcntl.LOCK_EX)

    def release(self):
        fcntl.flock(self.fd, fcntl.LOCK_UN)

    def close(self):
        self.fd.close()
        self.lockfile.unlink(missing_ok=True)

    def __enter__(self):
        self.acquire()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()

    def __del__(self):
        self.close()


class SharedMemoryWindowStorage(BaseWindowStorage):
    """Shared memory based window storage."""
    _dtype = np.uint64
    _ref_count_dtype = np.uint16

    def __init__(self, name: str, capacity: int, *, data: Optional[List[int]] = None, **kwargs) -> None:
        super().__init__(name, capacity)
        self._lock: GlobalLock = GlobalLock(name)
        # self._rlock = RLock()
        with self._lock:
            try:
                self._data_shm = SharedMemory(name=name)
                self._data: NDArray = np.ndarray(shape=(capacity,), dtype=self._dtype, buffer=self._data_shm.buf)
            except FileNotFoundError:
                self._data_shm = SharedMemory(name=name, create=True, size=np.dtype(self._dtype).itemsize * capacity)
                self._data: NDArray = np.ndarray(shape=(capacity,), dtype=self._dtype, buffer=self._data_shm.buf)
                self._data.fill(0)

            if data:
                if len(data) > self.capacity:
                    data = data[:self.capacity]
                self._data[:(len(data))] = data

            try:
                self._sum_shm = SharedMemory(name=f"{name}_sum")
            except FileNotFoundError:
                self._sum_shm = SharedMemory(name=f"{name}_sum", create=True, size=np.dtype(self._dtype).itemsize)
            self._sum: NDArray = np.ndarray(shape=(), dtype=self._dtype, buffer=self._sum_shm.buf)
            self._set_sum()

    @property
    def sum(self) -> int:
        with self._lock:
            return int(self._sum)

    def _set_sum(self) -> None:
        self._sum[...] = np.sum(self._data)

    def close(self):
        try:
            with self._lock:
                self._data_shm.close()
                self._data_shm.unlink()
                self._sum_shm.close()
                self._sum_shm.unlink()
            self._lock.close()
        except Exception as e:
            warnings.warn(f"Failed to close shared memory: {e}")

    def as_list(self) -> list:
        """Converts the contents of the shared array to a regular list.

        Returns:
            list: The contents of the shared array as a regular list.
        """
        with self._lock:
            return self._data[:-1].tolist()

    def clear(self) -> None:
        """Clears the contents of the shared array.

        Sets all elements of the shared array to zero. The operation is thread-safe.
        """
        with self._lock:
            self._data.fill(0)
            self._sum[...] = 0

    def slide(self, n: int) -> None:
        with self._lock:
            if n <= 0:
                pass
            if n >= self.capacity:
                self.clear()
                self._sum[...] = 0
            else:
                self._data[n:] = self._data[:-n]
                self._data[:n] = 0
                self._set_sum()

    def __getitem__(self, index):
        with self._lock:
            return int(self._data[index])

    def __setitem__(self, index, value):
        with self._lock:
            self._data[index] = value
            self._set_sum()

    def atomic_update(self, value: int, frame_limit: int, window_limit: int):
        """
        Атомарно увеличивает значение текущего кадра и обновляет сумму окна.
        Если при обновлении обнаруживается превышение лимитов, выбрасывается OverflowError.
        """
        with self._lock:
            current_value = int(self._data[0])
            new_value = current_value + value
            current_sum = int(self._sum)
            new_sum = current_sum + value

            if frame_limit > 0 and new_value > frame_limit:
                raise FrameLimitError("Frame limit exceeded")
            if window_limit > 0 and new_sum > window_limit:
                raise WindowLimitError("Window limit exceeded")

            self._data[0] = new_value
            self._sum[...] = new_sum
            return new_value
