"""
This module contains type definitions used in the library.

Types are defined to make function signatures more readable and to make it easier
to use type checkers and IDEs.

The types are also used in the documentation to make it easier to understand the
function signatures and the types of the parameters and the return values.
"""

from collections.abc import MutableSequence
from datetime import datetime
from enum import IntEnum, auto
from multiprocessing.shared_memory import ShareableList
from types import TracebackType
from typing import Any, NamedTuple, Optional, Protocol, Union

from typing_extensions import Literal


Sentinel = object()


class CallGateLimits(NamedTuple):
    """Representation of gate limits."""

    gate_limit: int
    frame_limit: int


class State(NamedTuple):
    """Representation of a gate storage state.

    Properties:
     - data: list of gate values
     - sum: sum of gate values
    """

    data: list
    sum: int


class GateStorageType(IntEnum):
    """gate storage type.

    - simple: simple in-memory storage (``collections.deque``)
    - shared: ``multiprocessing.ShareableList`` (can not contain integers higher than 2**64-1)
    - redis: Redis storage (needs ``redis`` (``redis-py``) package)
    """

    simple = auto()
    shared = auto()
    redis = auto()


class Frame(NamedTuple):
    """Representation of a gate frame.

    Properties:
     - dt: frame datetime
     - value: frame value
    """

    dt: datetime
    value: int


class LockProtocol(Protocol):  # noqa: D101
    def acquire(self, *args: Any, **kwargs: Any) -> Any: ...  # noqa: D102

    def release(self) -> None: ...  # noqa: D102

    def __enter__(self, *args: Any, **kwargs: Any) -> Any: ...

    def __exit__(
        self,
        exc_type: Optional[type[Exception]],
        exc_val: Optional[Exception],
        exc_tb: Optional[TracebackType],
    ) -> None: ...


class AsyncLockProtocol(Protocol):  # noqa: D101
    async def acquire(self, *args: Any, **kwargs: Any) -> Any: ...  # noqa: D102

    def release(self) -> None: ...  # noqa: D102

    async def __aenter__(self, *args: Any, **kwargs: Any) -> Any: ...

    async def __aexit__(
        self, exc_type: Optional[type[Exception]], exc_val: Optional[Exception], exc_tb: Optional[TracebackType]
    ) -> None: ...


LockType = Union[LockProtocol, AsyncLockProtocol]
StorageType = Union[MutableSequence, ShareableList, str]
GateStorageModeType = Union[GateStorageType, Literal["simple", "shared", "redis"]]
