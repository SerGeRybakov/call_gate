"""
Shared in-memory storage implementation using multiprocessing shared memory.

This storage is suitable for multiprocess applications. The storage uses a
multiprocessing Manager list in shared memory to store the values of the gate.
The list is divided into frames which are accessed by the index of the frame.

The storage is thread-safe and process-safe for multiple readers and writers.

The storage does not support persistence of the gate values. When the application
is restarted, the gate values are lost.
"""

from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from typing_extensions import Unpack

from call_gate.errors import CallGateValueError, FrameLimitError, FrameOverflowError, GateLimitError, GateOverflowError
from call_gate.storages.base_storage import BaseStorage
from call_gate.typings import State


if TYPE_CHECKING:
    from multiprocessing.managers import SyncManager


class SharedMemoryStorage(BaseStorage):
    """Shared in-memory storage implementation using multiprocessing shared memory.

    This storage is suitable for multiprocess applications. The storage uses a
    multiprocessing Manager list in shared memory to store the values of the gate.
    The list is divided into frames which are accessed by the index of the frame.

    The storage is thread-safe and process-safe for multiple readers and writers.

    The storage does not support persistence of the gate values. When the application
    is restarted, the gate values are lost.

    :param name: The name of the gate.
    :param capacity: The maximum number of values that the storage can store.
    :param data: Optional initial data for the storage.
    """

    def __init__(
        self, name: str, capacity: int, *, data: Optional[list[int]] = None, **kwargs: Unpack[dict[str, Any]]
    ) -> None:
        super().__init__(name, capacity, **kwargs)
        manager: SyncManager = kwargs.get("manager")
        with self._lock:
            if data:
                data = list(data)
                if len(data) != self.capacity:
                    if len(data) > self.capacity:
                        data = data[: self.capacity]
                    else:
                        diff = self.capacity - len(data)
                        data.extend([0] * diff)
                self._data = manager.list(data)
                self._sum = manager.Value("i", sum(self._data))
            else:
                self._data = manager.list([0] * capacity)
                self._sum = manager.Value("i", 0)

            # Initialize timestamp as shared Value (double for timestamp)
            self._timestamp = manager.Value("d", 0.0)

    @property
    def sum(self) -> int:
        """Get the current sum of the storage."""
        with self._rlock:
            with self._lock:
                return deepcopy(self._sum.value)

    @property
    def state(self) -> State:
        """Get the sum of all values in the storage."""
        with self._rlock:
            with self._lock:
                return State(data=list(self._data), sum=int(self._sum.value))

    def close(self) -> None:
        """Close storage memory segment."""
        pass

    def as_list(self) -> list:
        """Get the contents of the shared array as a regular list."""
        with self._rlock:
            with self._lock:
                return deepcopy(self._data)

    def clear(self) -> None:
        """Clear the contents of the shared array.

        Sets all elements of the shared array to zero. The operation is thread-safe.
        """
        with self._rlock:
            with self._lock:
                self._data[:] = [0] * self.capacity
                self._sum.value = 0
                self._timestamp.value = 0.0

    def slide(self, n: int) -> None:
        """Slide data to the right by n frames.

        The skipped frames are filled with zeros.
        :param n: The number of frames to slide
        :return: the sum of the removed elements' values
        """
        with self._rlock:
            with self._lock:
                if n < 1:
                    raise CallGateValueError("Value must be >= 1.")
                if n >= self.capacity:
                    self.clear()
                else:
                    self._data[n:] = self._data[:-n]
                    self._data[:n] = [0] * n
                    self._sum.value = sum(self._data)

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
        with self._rlock:
            with self._lock:
                current_value = int(self._data[0])
                new_value = current_value + value
                new_sum = self._sum.value + value

                if 0 < frame_limit < new_value:
                    raise FrameLimitError("Frame limit exceeded")
                if 0 < gate_limit < new_sum:
                    raise GateLimitError("Gate limit exceeded")
                if new_sum < 0:
                    raise GateOverflowError("Gate sum value must be >= 0.")
                if new_value < 0:
                    raise FrameOverflowError("Frame value must be >= 0.")

                self._data[0] = new_value
                self._sum.value = new_sum

    def get_timestamp(self) -> Optional[datetime]:
        """Get the last update timestamp from storage.

        :return: The last update timestamp, or None if not set.
        """
        with self._rlock:
            with self._lock:
                ts = self._timestamp.value
                return datetime.fromtimestamp(ts) if ts > 0 else None

    def set_timestamp(self, dt: datetime) -> None:
        """Save the timestamp to storage.

        :param dt: The timestamp to save.
        """
        with self._rlock:
            with self._lock:
                self._timestamp.value = dt.timestamp()

    def clear_timestamp(self) -> None:
        """Clear the timestamp from storage."""
        with self._rlock:
            with self._lock:
                self._timestamp.value = 0.0

    def __getitem__(self, index: int) -> int:
        with self._rlock:
            with self._lock:
                return int(self._data[index])
