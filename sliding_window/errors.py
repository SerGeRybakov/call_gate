"""
This module contains all the custom exceptions used in the library.

The exceptions are used to notify the caller about different types of errors
that can occur during the execution of the library code.

The exceptions can be divided into two categories: errors that are raised
synchronously and errors that are raised asynchronously.

The synchronous errors are raised immediately by the library code and are
propagated up the call stack. The asynchronous errors are raised by the
asynchronous code and are propagated up the call stack by the means of the
asyncio library.

The library exceptions are derived from the Exception class and contain the
following information:
  - A message describing the error
  - A reference to the window object that raised the error (if applicable)
"""

from typing import TYPE_CHECKING, Any, Optional

from typing_extensions import Unpack


if TYPE_CHECKING:
    from sliding_window.window import SlidingWindow

__all__ = [
    "FrameLimitError",
    "FrameOverflowError",
    "SlidingWindowBaseError",
    "SlidingWindowImportError",
    "SlidingWindowOverflowError",
    "SlidingWindowTypeError",
    "SlidingWindowValueError",
    "SpecialSlidingWindowError",
    "ThrottlingError",
    "WindowLimitError",
    "WindowOverflowError",
]


class SlidingWindowBaseError(Exception):
    """Base error for all errors explicitly raised within the library."""


class SlidingWindowImportError(SlidingWindowBaseError, ImportError):
    """Import error."""


class SlidingWindowValueError(SlidingWindowBaseError, ValueError):
    """Value error."""


class SlidingWindowTypeError(SlidingWindowBaseError, TypeError):
    """Type error."""


class SpecialSlidingWindowError(SlidingWindowBaseError):
    """Base error for all errors explicitly raised within the library."""

    def __init__(
        self,
        message: str,
        window: Optional["SlidingWindow"] = None,
        *args: Unpack[tuple[Any, ...]],
        **kwargs: Unpack[dict[str, Any]],
    ) -> None:
        super().__init__(message, *args, **kwargs)  # type: ignore[arg-type]
        self.window = window
        self.message = message


class SlidingWindowOverflowError(SpecialSlidingWindowError, OverflowError):
    """Overflow error."""


class WindowOverflowError(SlidingWindowOverflowError):
    """Window overflow error."""


class FrameOverflowError(SlidingWindowBaseError):
    """Frame overflow error."""


class ThrottlingError(SpecialSlidingWindowError):
    """Base limit error, raised when rate limits are reached or violated."""


class FrameLimitError(ThrottlingError):
    """Custom limit error, raised when frame limit is reached or violated."""


class WindowLimitError(ThrottlingError):
    """Custom limit error, raised when window limit is reached or violated."""
