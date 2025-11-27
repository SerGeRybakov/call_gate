"""
Simple in-memory storage implementation using a collections.deque as underlying container.

This storage is suitable for single-threaded applications or applications that do not share
the storage between threads or processes.

The storage uses a queue to store the values of the gate. The queue is implemented as a double-ended
queue (deque) with a maximum size equal to the gate size. The elements of the deque are the
values of the gate, where the first element is the value of the most recent frame and the last
element is the value of the oldest frame.

The storage is thread-safe for multiple readers and writers.

If the gate is used in a distributed application, the caller must ensure that the gate is not
accessed concurrently by multiple processes for writing and that the gate is properly synchronized
between processes.

The storage does not support persistence of the gate values. When the application is restarted,
the gate values are lost.
"""

from collections import deque
from datetime import datetime
from typing import Any, Optional

from typing_extensions import Unpack

from call_gate.errors import (
    CallGateValueError,
    FrameLimitError,
    FrameOverflowError,
    GateLimitError,
    GateOverflowError,
)
from call_gate.storages.base_storage import BaseStorage
from call_gate.typings import State


class SimpleStorage(BaseStorage):
    """Simple in-memory storage implementation using a ``collections.deque`` as underlying container.

    This storage is suitable for multithreaded applications or applications that do not share
    the gate between processes.

    The storage uses a queue to store the values of the gate. The queue is implemented as a double-ended
    queue (deque) with a maximum size equal to the gate size. The elements of the deque are the
    values of the gate, where the first element is the value of the most recent frame and the last
    element is the value of the oldest frame.

    The storage is thread-safe for multiple readers and  writers.

    If the gate is used in a distributed application, the caller must ensure that the gate is not
    accessed concurrently by multiple processes for writing and that the gate is properly synchronized
    between processes.

    The storage does not support persistence of the gate values. When the application is restarted,
    the gate values are lost.

    :param name: The name of the gate.
    :param capacity: The maximum number of values that the storage can store.
    :param data: Optional initial data for the storage.
    """

    def __get_clear_deque(self) -> deque:
        return deque([0] * self.capacity, maxlen=self.capacity)

    def __init__(
        self, name: str, capacity: int, *, data: Optional[list[int]] = None, **kwargs: Unpack[dict[str, Any]]
    ) -> None:
        super().__init__(name, capacity, **kwargs)
        with self._lock:
            if data:
                data = list(data)
                if len(data) != self.capacity:
                    if len(data) > self.capacity:
                        data = data[: self.capacity]
                    else:
                        diff = self.capacity - len(data)
                        data.extend([0] * diff)
                self._data = deque(data)
            else:
                self._data: deque = self.__get_clear_deque()

            self._sum = sum(self._data)
            self._timestamp: Optional[datetime] = None

    @property
    def sum(self) -> int:
        """Get the sum of all values in the storage."""
        with self._rlock:
            with self._lock:
                return self._sum

    @property
    def state(self) -> State:
        """Get the current state of the storage."""
        with self._rlock:
            with self._lock:
                lst = list(self._data)
                return State(data=lst, sum=int(sum(lst)))

    def slide(self, n: int) -> None:
        """Slide storage data to the right by n frames.

        The skipped frames are filled with zeros.
        :param n: The number of frames to slide.
        :return: The sum of the removed elements' values.
        """
        with self._lock:
            if n < 1:
                raise CallGateValueError("Value must be >= 1.")
            if n >= self.capacity:
                self.clear()
            self._data.extendleft([0] * n)

    def as_list(self) -> list:
        """Convert the contents of the storage data to a regular list."""
        with self._rlock:
            with self._lock:
                return list(self._data)

    def clear(self) -> None:
        """Clear the data contents (resets all values to 0)."""
        with self._rlock:
            with self._lock:
                self._data = self.__get_clear_deque()
                self._sum = 0
                self._timestamp = None

    def atomic_update(self, value: int, frame_limit: int, gate_limit: int) -> None:
        """Atomically update the value of the most recent frame and the storage sum.

        If the new value of the most recent frame or the storage sum exceeds the corresponding limit,
        the method raises a FrameLimitError or GateLimitError exception.

        If the new value of the most recent frame or the storage sum is less than 0,
        the method raises a CallGateOverflowError exception.

        :param value: The value to add to the most recent frame value.
        :param frame_limit: The maximum allowed value of the most recent frame.
        :param gate_limit: The maximum allowed value of the storage sum.
        :raises FrameLimitError: If the new value of the most recent frame exceeds the frame limit.
        :raises GateLimitError: If the new value of the storage sum exceeds the gate limit.
        :raises CallGateOverflowError: If the new value of the most recent frame or the storage sum is less than 0.
        :return: The new value of the most recent frame.
        """
        with self._lock:
            current_value = self._data[0]
            new_value = current_value + value
            current_sum = sum(self._data)
            new_sum = current_sum + value

            if 0 < frame_limit < new_value:
                raise FrameLimitError("Frame limit exceeded")
            if 0 < gate_limit < new_sum:
                raise GateLimitError("Gate limit exceeded")
            if new_sum < 0:
                raise GateOverflowError("Gate sum value must be >= 0.")
            if new_value < 0:
                raise FrameOverflowError("Frame value must be >= 0.")

            self._data[0] = new_value
            self._sum = new_sum

    def get_timestamp(self) -> Optional[datetime]:
        """Get the last update timestamp from storage.

        :return: The last update timestamp, or None if not set.
        """
        with self._rlock:
            with self._lock:
                return self._timestamp

    def set_timestamp(self, dt: datetime) -> None:
        """Save the timestamp to storage.

        :param dt: The timestamp to save.
        """
        with self._rlock:
            with self._lock:
                self._timestamp = dt

    def clear_timestamp(self) -> None:
        """Clear the timestamp from storage."""
        with self._rlock:
            with self._lock:
                self._timestamp = None

    def __getitem__(self, index: int) -> int:
        with self._rlock:
            return int(self._data[index])
