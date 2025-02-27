from collections.abc import MutableSequence
from datetime import datetime
from enum import IntEnum, auto
from multiprocessing.shared_memory import ShareableList
from types import TracebackType
from typing import TYPE_CHECKING, Any, Dict, NamedTuple, Optional, Protocol, Type, Union

from typing_extensions import Literal, Unpack


Sentinel = object()

if TYPE_CHECKING:
    try:
        from numpy.typing import NDArray
    except ImportError:
        NDArray = Sentinel


class WindowStorageMode(IntEnum):
    """Window storage storage.

    - simple: simple in-memory storage (``collections.deque``)
    - shared: ``multiprocessing.ShareableList`` (can not contain integers higher than 2**64-1)
    - redis: Redis storage (needs ``redis`` (``redis-py``) package)
    """

    simple = auto()
    shared = auto()
    redis = auto()


class Frame(NamedTuple):
    """Representation of a window frame.

    Properties:
     - dt: frame datetime
     - value: frame value
    """

    dt: datetime
    value: int


class LockProtocol(Protocol):
    def acquire(self, *args: Any, **kwargs: Any) -> Any: ...

    def release(self) -> None: ...

    def __enter__(self, *args: Any, **kwargs: Any) -> Any: ...

    def __exit__(
        self,
        exc_type: Optional[Type[Exception]],
        exc_val: Optional[Exception],
        exc_tb: Optional[TracebackType],
    ) -> None: ...


class AsyncLockProtocol(Protocol):
    async def acquire(self, *args: Any, **kwargs: Any) -> Any: ...

    def release(self) -> None: ...

    async def __aenter__(self, *args: Any, **kwargs: Any) -> Any: ...

    async def __aexit__(
        self, exc_type: Optional[Type[Exception]], exc_val: Optional[Exception], exc_tb: Optional[TracebackType]
    ) -> None: ...


LockType = Union[LockProtocol, AsyncLockProtocol]
StorageType = Union[MutableSequence, ShareableList, "NDArray", str]
WindowStorageModeType = Union[WindowStorageMode, Literal["simple", "shared", "redis"]]
KWType = Unpack[dict[str, Any]]
