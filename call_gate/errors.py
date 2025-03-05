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
  - A reference to the gate object that raised the error (if applicable)
"""

from typing import TYPE_CHECKING, Any, Optional

from typing_extensions import Unpack


if TYPE_CHECKING:
    from call_gate.gate import CallGate

__all__ = [
    "CallGateBaseError",
    "CallGateImportError",
    "CallGateOverflowError",
    "CallGateTypeError",
    "CallGateValueError",
    "FrameLimitError",
    "FrameOverflowError",
    "GateLimitError",
    "GateOverflowError",
    "SpecialCallGateError",
    "ThrottlingError",
]


class CallGateBaseError(Exception):
    """Base error for all errors explicitly raised within the library."""


class CallGateImportError(CallGateBaseError, ImportError):
    """Import error."""


class CallGateValueError(CallGateBaseError, ValueError):
    """Value error."""


class CallGateTypeError(CallGateBaseError, TypeError):
    """Type error."""


class SpecialCallGateError(CallGateBaseError):
    """Base error for all errors explicitly raised within the library."""

    def __init__(
        self,
        message: str,
        gate: Optional["CallGate"] = None,
        *args: Unpack[tuple[Any, ...]],
        **kwargs: Unpack[dict[str, Any]],
    ) -> None:
        super().__init__(message, *args, **kwargs)  # type: ignore[arg-type]
        self.gate = gate
        self.message = message


class CallGateOverflowError(SpecialCallGateError, OverflowError):
    """Overflow error, raised when the value is less than 0."""


class GateOverflowError(CallGateOverflowError):
    """Gate overflow error, raised when the value is less than 0."""


class FrameOverflowError(CallGateOverflowError):
    """Frame overflow error, raised when the value is less than 0."""


class ThrottlingError(SpecialCallGateError):
    """Base limit error, raised when rate limits are reached or violated."""


class FrameLimitError(ThrottlingError):
    """Custom limit error, raised when frame limit is reached or violated."""


class GateLimitError(ThrottlingError):
    """Custom limit error, raised when gate limit is reached or violated."""
