"""
Base classes for gate storages.

This module contains base classes for gate storages. Storages are responsible
for storing and retrieving gate data. There are two types of storages: simple
and shared. Simple storages store data in memory and are not thread-safe.
Shared storages store data in shared memory and are thread-safe and process-safe.
"""

import atexit
import multiprocessing

from abc import ABC, abstractmethod
from multiprocessing.managers import SyncManager
from typing import Any, Optional

from typing_extensions import Unpack

from call_gate.typings import State


multiprocessing.set_start_method("spawn", force=True)

# Global manager for the entire application
_GLOBAL_MANAGER: Optional[SyncManager] = None


def get_global_manager() -> SyncManager:
    """Return a global instance of Manager(), creating it only once."""
    global _GLOBAL_MANAGER  # noqa: PLW0603
    if _GLOBAL_MANAGER is None:
        _GLOBAL_MANAGER = multiprocessing.Manager()
        atexit.register(_GLOBAL_MANAGER.shutdown)
    return _GLOBAL_MANAGER


class BaseStorage(ABC):
    """BaseStorage class.

    This class is a base for all  storages.
    It provides a base interface and common methods for all storages.
    """

    _data: Any
    _sum: Any

    def __init__(self, name: str, capacity: int, *, data: Optional[list[int]] = None, **kwargs: Unpack[dict[str, Any]]):
        self.name = name
        self.capacity = capacity
        manager = kwargs.get("manager")
        self._lock = manager.Lock()
        self._rlock = manager.RLock()

    @abstractmethod
    def slide(self, n: int) -> int:
        """Slide storage data to the right by n frames.

        The skipped frames are filled with zeros.
        :param n: The number of frames to slide
        :return: the sum of the removed elements' values
        """
        pass

    @property
    @abstractmethod
    def state(self) -> State:
        """Get the current state of the storage."""
        pass

    @property
    @abstractmethod
    def sum(self) -> int:
        """Get the sum of all values in the storage."""
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    def as_list(self) -> list:
        """Convert the contents of the storage data to a regular list."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clear the data contents (resets all values to ``0``)."""
        pass

    @abstractmethod
    def __getitem__(self, index: int) -> int:
        """Get the value from the index of the storage.

        :param index: Ignored; the operation always affects the head (index 0).
        """
        pass

    def __bool__(self) -> bool:
        return bool(self.sum)
