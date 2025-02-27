"""
Simple in-memory window storage implementation using a collections.deque as underlying container.

This storage is suitable for single-threaded applications or applications that do not share
the window between threads or processes.

The storage uses a queue to store the values of the window. The queue is implemented as a double-ended
queue (deque) with a maximum size equal to the window size. The elements of the deque are the
values of the window, where the first element is the value of the most recent frame and the last
element is the value of the oldest frame.

The storage is thread-safe for multiple readers but not for multiple writers. If the window is used
in a multithreaded application, the caller must ensure that the window is not accessed concurrently
by multiple threads.

If the window is used in a distributed application, the caller must ensure that the window is not
accessed concurrently by multiple processes and that the window is properly synchronized between
processes.

The storage does not support persistence of the window values. When the application is restarted,
the window values are lost.
"""

from collections import deque
from threading import Lock, RLock
from typing import Optional

from sliding_window.errors import (
    FrameLimitError,
    FrameOverflowError,
    SlidingWindowValueError,
    WindowLimitError,
    WindowOverflowError,
)
from sliding_window.storages.base_storage import BaseWindowStorage
from sliding_window.typings import WindowState


class SimpleWindowStorage(BaseWindowStorage):
    """Simple in-memory window storage implementation using a ``collections.deque`` as underlying container.

    This storage is suitable for single-threaded applications or applications that do not share
    the window between threads or processes.

    The storage uses a queue to store the values of the window. The queue is implemented as a double-ended
    queue (deque) with a maximum size equal to the window size. The elements of the deque are the
    values of the window, where the first element is the value of the most recent frame and the last
    element is the value of the oldest frame.

    The storage is thread-safe for multiple readers but not for multiple writers. If the window is used
    in a multithreaded application, the caller must ensure that the window is not accessed concurrently
    by multiple threads.

    If the window is used in a distributed application, the caller must ensure that the window is not
    accessed concurrently by multiple processes and that the window is properly synchronized between
    processes.

    The storage does not support persistence of the window values. When the application is restarted,
    the window values are lost.

    :param name: The name of the window.
    :param capacity: The maximum number of values that the window can store.
    :param data: Optional initial data for the window.
    """

    def __get_clear_deque(self) -> deque:
        return deque([0] * self.capacity, maxlen=self.capacity)

    def __init__(self, name: str, capacity: int, *, data: Optional[list[int]] = None) -> None:
        super().__init__(name, capacity)
        self._lock: Lock = Lock()
        self._rlock: RLock = RLock()
        with self._lock:
            self._data: deque = self.__get_clear_deque()
            if data:
                self._data.extendleft(data)

    @property
    def sum(self) -> int:
        """Get the sum of all values in the storage."""
        with self._rlock:
            return sum(self._data)

    @property
    def state(self) -> WindowState:
        """Get the current state of the storage."""
        with self._rlock:
            with self._lock:
                lst = list(self._data)
                return WindowState(data=lst, sum=int(sum(lst)))

    def close(self) -> None:
        """Close storage memory segment."""
        self._data.clear()

    def slide(self, n: int) -> None:
        """Slide window data to the right by n frames.

        The skipped frames are filled with zeros.
        :param n: The number of frames to slide.
        :return: The sum of the removed elements' values.
        """
        with self._lock:
            if n < 1:
                raise SlidingWindowValueError("Value must be >= 1.")
            self._data.extendleft([0] * n)

    def as_list(self) -> list:
        """Convert the contents of the storage data to a regular list."""
        with self._rlock:
            return list(self._data)

    def clear(self) -> None:
        """Clear the data contents (resets all values to 0)."""
        with self._lock:
            self._data = self.__get_clear_deque()

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
        with self._lock:
            current_value = self._data[0]
            new_value = current_value + value
            current_sum = sum(self._data)
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
            return new_value

    def __getitem__(self, index: int) -> int:
        with self._rlock:
            return int(self._data[index])

    def __setitem__(self, index: int, value: int) -> None:
        with self._lock:
            self._data[index] = value
