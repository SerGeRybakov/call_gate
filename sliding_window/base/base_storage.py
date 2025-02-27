from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from typing_extensions import Unpack, Optional

from sliding_window.typings import LockType, StorageType


class BaseWindowStorage(ABC):
    """Base class for window storages."""

    _lock: LockType
    _rlock: LockType
    _data: StorageType
    _sum: Optional[int] = None

    def __init__(self, name: str, capacity: int, *, data: list[int] | None = None, **kwargs: Unpack[dict[str, Any]]):
        self.name = name
        self.capacity = capacity

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
    def sum(self):
        """Return the sum of all values in the storage."""
        pass

    @abstractmethod
    def atomic_update(self, value: int, frame_limit: int, window_limit: int) -> None:
        """Make an atomic update to the storage head frame and sum."""
        pass

    @abstractmethod
    def as_list(self) -> list:
        """Converts the contents of the storage data to a regular list."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clears the data contents (resets all values to ``0``)."""
        pass

    @abstractmethod
    def close(self):
        """Close shared memory segment."""
        pass

    def __del__(self):
        self.close()

    @abstractmethod
    def __getitem__(self, index: int) -> int:
        pass

    @abstractmethod
    def __setitem__(self, index: int, value: int) -> None:
        pass

    def __bool__(self) -> bool:
        return bool(self.sum)
