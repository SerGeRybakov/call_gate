from typing import TYPE_CHECKING, Any, Optional

from typing_extensions import Unpack

from sliding_window.typings import KWType


if TYPE_CHECKING:
    from sliding_window.window import SlidingWindow


class SlidingWindowBaseError(Exception):
    """Base error for all errors explicitly raised within the library."""


class SlidingWindowImportError(SlidingWindowBaseError, ImportError):
    """Import error."""


class SlidingWindowValueError(SlidingWindowBaseError, ValueError):
    """Value error."""


class SlidingWindowTypeError(SlidingWindowBaseError, TypeError):
    """Type error."""


class ThrottlingError(SlidingWindowBaseError):
    """Base limit error, raised when rate limits are reached or violated."""

    def __init__(self, message: str, window: Optional["SlidingWindow"] = None, *args: Unpack[tuple[Any, ...]], **kwargs: KWType) -> None:
        super().__init__(message, *args, **kwargs)  # type: ignore[arg-type]
        self.window = window
        self.message = message


class FrameLimitError(ThrottlingError):
    """Custom limit error, raised when frame limit is reached or violated."""


class WindowLimitError(ThrottlingError):
    """Custom limit error, raised when window limit is reached or violated."""


__all__ = [
    SlidingWindowBaseError,
    SlidingWindowTypeError,
    SlidingWindowImportError,
    SlidingWindowValueError,
    ThrottlingError,
    FrameLimitError,
    WindowLimitError,
]
