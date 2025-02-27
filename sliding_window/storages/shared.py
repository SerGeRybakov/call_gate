"""
Shared in-memory window storage implementation using multiprocessing shared memory.

This storage is suitable for multiprocess applications. The storage uses a numpy
array in shared memory to store the values of the window. The array is divided into
frames which are accessed by the index of the frame.

The storage is thread-safe and process-safe for multiple readers and writers.

The storage does not support persistence of the window values. When the application
is restarted, the window values are lost.
"""

import fcntl

from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
from threading import RLock
from types import TracebackType
from typing import TYPE_CHECKING, Any, Optional, TextIO

import numpy as np

from typing_extensions import Unpack

from sliding_window import FrameLimitError, WindowLimitError
from sliding_window.errors import FrameOverflowError, WindowOverflowError
from sliding_window.storages.base_storage import BaseWindowStorage, _mute
from sliding_window.typings import WindowState


if TYPE_CHECKING:
    from numpy.typing import NDArray


class GlobalLock:
    """Global lock with file-based locking for processes."""

    def _open(self) -> None:
        """Open the lockfile if it's not opened yet."""
        if self.fd is None:
            self.fd: TextIO = self.lockfile.open(mode="w", encoding="utf-8")

    def __init__(self, name: str):
        self.lockfile = Path(f".{name}.lock")
        self.fd: Optional[TextIO] = None
        self._open()

    def __del__(self) -> None:
        self.close()

    def acquire(self) -> None:
        """Acquire the lock."""
        fcntl.flock(self.fd.fileno(), fcntl.LOCK_EX)

    def release(self) -> None:
        """Release the lock."""
        fcntl.flock(self.fd.fileno(), fcntl.LOCK_UN)

    def close(self) -> None:
        """Close the lockfile."""
        if self.fd:
            self.fd.close()
            self.fd = None
            self.lockfile.unlink(missing_ok=True)

    def __enter__(self) -> None:
        self._open()
        self.acquire()

    def __exit__(
        self, exc_type: Optional[type[Exception]], exc_val: Optional[Exception], exc_tb: Optional[TracebackType]
    ) -> None:
        self.release()


class SharedMemoryWindowStorage(BaseWindowStorage):
    """Shared in-memory window storage implementation using multiprocessing shared memory.

    This storage is suitable for multiprocess applications. The storage uses a numpy
    array in shared memory to store the values of the window. The array is divided into
    frames which are accessed by the index of the frame.

    The storage is thread-safe and process-safe for multiple readers and writers.

    The storage does not support persistence of the window values. When the application
    is restarted, the window values are lost.

    :param name: The name of the window.
    :param capacity: The maximum number of values that the window can store.
    :param data: Optional initial data for the window.
    """

    _dtype = np.uint64
    _ref_count_dtype = np.uint16

    def _set_sum(self) -> None:
        self._sum[...] = np.sum(self._data)

    def __init__(
        self, name: str, capacity: int, *, data: Optional[list[int]] = None, **kwargs: Unpack[dict[str, Any]]
    ) -> None:
        super().__init__(name, capacity)
        self._lock: GlobalLock = GlobalLock(name)
        self._rlock = RLock()
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
                    data = data[: self.capacity]
                self._data[: (len(data))] = data

            try:
                self._sum_shm = SharedMemory(name=f"{name}_sum")
            except FileNotFoundError:
                self._sum_shm = SharedMemory(name=f"{name}_sum", create=True, size=np.dtype(self._dtype).itemsize)
            self._sum: NDArray = np.ndarray(shape=(), dtype=self._dtype, buffer=self._sum_shm.buf)
            self._set_sum()

    @property
    def sum(self) -> int:
        """Get the current sum of the storage."""
        with self._rlock:
            with self._lock:
                return int(self._sum)

    @property
    def state(self) -> WindowState:
        """Get the sum of all values in the storage."""
        with self._rlock:
            with self._lock:
                return WindowState(data=self._data.tolist(), sum=int(self._sum))

    def close(self) -> None:
        """Close storage memory segment."""
        with self._rlock:
            with self._lock:
                self._data_shm.close()
                _mute(self._data_shm.unlink)
                self._sum_shm.close()
                _mute(self._sum_shm.unlink)
            self._lock.close()

    def as_list(self) -> list:
        """Get the contents of the shared array as a regular list."""
        with self._rlock:
            with self._lock:
                return self._data[:-1].tolist()

    def clear(self) -> None:
        """Clear the contents of the shared array.

        Sets all elements of the shared array to zero. The operation is thread-safe.
        """
        with self._rlock:
            with self._lock:
                self._data.fill(0)
                self._sum[...] = 0

    def slide(self, n: int) -> None:
        """Slide window data to the right by n frames.

        The skipped frames are filled with zeros.
        :param n: The number of frames to slide
        :return: the sum of the removed elements' values
        """
        with self._rlock:
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

    def atomic_update(self, value: int, frame_limit: int, window_limit: int) -> None:
        """Atomically update the value of the most recent frame and the window sum.

        If the new value of the most recent frame or the window sum exceeds the corresponding limit,
        the method raises a FrameLimitError or WindowLimitError exception.

        If the new value of the most recent frame or the window sum is less than 0,
        the method raises a SlidingWindowOverflowError exception.

        :param value: The value to add to the most recent frame value.
        :param frame_limit: The maximum allowed value of the most recent frame.
        :param window_limit: The maximum allowed value of the window sum.
        :raises FrameLimitError: If the new value of the most recent frame exceeds the frame limit.
        :raises WindowLimitError: If the new value of the window sum exceeds the window limit.
        :raises SlidingWindowOverflowError: If the new value of the most recent frame or the window sum is less than 0.
        :return: The new value of the most recent frame.
        """
        with self._rlock:
            with self._lock:
                current_value = int(self._data[0])
                new_value = current_value + value
                current_sum = int(self._sum)
                new_sum = current_sum + value

                if 0 < frame_limit < new_value:
                    raise FrameLimitError("Frame limit exceeded")
                if 0 < window_limit < new_sum:
                    raise WindowLimitError("Window limit exceeded")
                if new_sum < 0:
                    raise WindowOverflowError("Window sum value must be >= 0.")
                if new_value < 0:
                    raise FrameOverflowError("Frame value must be >= 0.")

                self._data[0] = new_value
                self._sum[...] = new_sum

    def __getitem__(self, index: int) -> int:
        with self._rlock:
            with self._lock:
                return int(self._data[index])

    def __setitem__(self, index: int, value: int) -> None:
        with self._rlock:
            with self._lock:
                self._data[index] = value
                self._set_sum()
