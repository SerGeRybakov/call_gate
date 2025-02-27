"""
Base classes for window storages.

This module contains base classes for window storages. Storages are responsible
for storing and retrieving window data. There are two types of storages: simple
and shared. Simple storages store data in memory and are not thread-safe.
Shared storages store data in shared memory and are thread-safe.

The base class for all storages is :class:`BaseWindowStorage`. It defines the
interface for all storages. The base class for simple storages is
:class:`SimpleWindowStorage`, and the base class for shared storages is
:class:`SharedWindowStorage`.

The base class for all locks is :class:`BaseLock`. It defines the interface for
all locks. The base class for simple locks is :class:`SimpleLock`, and the base
class for shared locks is :class:`SharedLock`.
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

from typing_extensions import Unpack

from sliding_window.typings import LockType, StorageType, WindowState


def _mute(method: Callable) -> Any:
    try:
        method()
    except (FileNotFoundError, ImportError, TypeError, ValueError):
        pass
    except Exception:
        raise


class BaseWindowStorage(ABC):
    """BaseWindowStorage class.

    This class is a base for all window storages.
    It provides a base interface and common methods for all window storages.
    """

    _lock: LockType
    _rlock: LockType
    _data: StorageType
    _sum: Optional[int] = None

    def __init__(self, name: str, capacity: int, *, data: Optional[list[int]] = None, **kwargs: Unpack[dict[str, Any]]):
        self.name = name
        self.capacity = capacity

    def __del__(self) -> None:
        _mute(self.close)

    @abstractmethod
    def slide(self, n: int) -> int:
        """Slide window data to the right by n frames.

        The skipped frames are filled with zeros.
        :param n: The number of frames to slide
        :return: the sum of the removed elements' values
        """
        pass

    @property
    @abstractmethod
    def state(self) -> WindowState:
        """Get the current state of the storage."""
        pass

    @property
    @abstractmethod
    def sum(self) -> int:
        """Get the sum of all values in the storage."""
        pass

    @abstractmethod
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
    def close(self) -> None:
        """Close storage memory segment."""
        pass

    @abstractmethod
    def __getitem__(self, index: int) -> int:
        """Get the value from the index of the sliding window.

        :param index: Ignored; the operation always affects the head (index 0).
        """
        pass

    @abstractmethod
    def __setitem__(self, index: int, value: int) -> None:
        """Replace the value at the index of the sliding window, automatically updating the window's sum.

        :param index: Ignored; the operation always affects the head (index 0).
        :param value: The new integer value to set at index 0.
        """
        pass

    def __bool__(self) -> bool:
        return bool(self.sum)
