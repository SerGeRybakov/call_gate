"""
This module implements a thread-safe, process-safe, coroutine-sage distributed time-bound rate limit counter.

The main class provided is `CallGate`, which allows tracking events over a configurable time gate
divided into equal frames. Each frame tracks increments and decrements within a specific time period
defined by the `frame_step`. The gate maintains only the values within the gate bounds, automatically
removing outdated frames as new periods start.

Features:
  - Automatically manages frame data based on the current time and gate configuration.
  - Supports limits on both frame and gate values, raising `FrameLimitError` or `GateLimitError` if exceeded.
  - Provides various data storage options, including in-memory, shared memory, and Redis.
  - Includes error handling for common scenarios, with specific exceptions derived from base errors within the library.

Optional dependencies:
  - `redis` for Redis-based storage.
"""

import json
import time

from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union
from zoneinfo import ZoneInfo

from call_gate.errors import (
    CallGateImportError,
    CallGateTypeError,
    CallGateValueError,
    FrameLimitError,
    GateLimitError,
    SpecialCallGateError,
    ThrottlingError,
)
from call_gate.storages.base_storage import BaseStorage, get_global_manager
from call_gate.storages.shared import SharedMemoryStorage
from call_gate.storages.simple import SimpleStorage
from call_gate.sugar import _CallGateWrapper, dual
from call_gate.typings import (
    CallGateLimits,
    Frame,
    GateStorageModeType,
    GateStorageType,
    Sentinel,
    State,
)


if TYPE_CHECKING:
    import asyncio

    from concurrent.futures.thread import ThreadPoolExecutor


try:
    import redis
except ImportError:
    redis = Sentinel


class CallGate:
    """CallGate is a thread-safe, process-safe, coroutine-sage distributed time-bound rate limit counter.

    The gate is divided into equal frames basing on the gate size and frame step.
    Each frame is bound to the frame_step set frame step and keeps track of increments and decrements
    within a time period equal to the frame step. Values in the ``data[0]`` are always bound
    to the current granular time frame step. Tracking timestamp may be bound to a personalized timezone.

    The gate keeps only those values which are within the gate bounds. The old values are removed
    automatically when the gate is full and the new frame period started.

    The sum of the frames values increases while the gate is not full. When it's full, the sum will
    decrease on each slide (due to erasing of the outdated frames) and increase again on each increment.

    If the gate was not used for a while and some (or all) frames are outdated and a new increment
    is made, the outdated frames will be replaced with the new period from the current moment
    up to the last valid timestamp (if there is one). In other words, on increment the gate always
    keeps frames from the current moment back to history, ordered by granular frame step without any gaps.

    If any of gate or frame limit is set and  any of these limits are exceeded, ``GateLimitError``
    or ``FrameLimitError`` (derived from ``ThrottlingError``) will be thrown.
    The error provides the information of the exceeded limit type and its value.

    Also, the gate may throw its own exceptions derived from ``CallGateBaseError``. Each of them
    also originates from Python typical native exceptions: ``ValueError``, ``TypeError``, ``ImportError``.

    The gate has 3 types of data storage:
        - ``GateStorageType.simple`` (default) - stores data in a ``collections.deque``.

        - ``GateStorageType.shared`` - stores data in a piece of memory that is shared between processes
        and threads started from one parent process/thread.

        - ``GateStorageType.redis`` (requires ``redis`` (``redis-py``) - stores data in Redis,
          what provides a distributed storage between multiple processes, servers and Docker containers.

    CallGate constructor accepts ``**kwargs`` for ``GateStorageType.redis`` storage. The parameters described
    at https://redis.readthedocs.io/en/latest/connections.html for ``redis.Redis`` object can be passed
    as keyword arguments. Redis URL is not supported. If not provided, the gate will use the default
    connection parameters, except the ``db``, which is set to ``15``.

    :param name: gate name
    :param gate_size: The total size of the gate (as a timedelta or number of seconds).
    :param frame_step: The granularity of each frame in the gate (either as a timedelta or seconds).
    :param gate_limit: Maximum allowed sum of values across the gate, default is ``0`` (no limit).
    :param frame_limit: Maximum allowed value per frame in the gate, default is ``0`` (no limit).
    :param timezone: Timezone name ("UTC", "Europe/Rome") for handling frames timestamp, default is ``None``.
    :param storage: Type of data storage: one of GateStorageType keys, default is ``GateStorageType.simple``.
    :param kwargs: Special parameters for storage.
    """

    @staticmethod
    def _is_int(value: Any) -> bool:
        return value is not None and not isinstance(value, bool) and isinstance(value, int)

    @staticmethod
    def _validate_and_set_gate_and_granularity(gate_size: Any, step: Any) -> tuple[timedelta, timedelta]:
        # If gate_size is an int or float, convert it to a timedelta using seconds.
        if isinstance(gate_size, (int, float)):
            gate_size = timedelta(seconds=gate_size)
        # Similarly, if step is an int or float, convert it to a timedelta using seconds.
        if isinstance(step, (int, float)):
            step = timedelta(seconds=step)
        # Check that the step is less than the gate size.
        if step >= gate_size:
            raise CallGateValueError("The frame step must be less than the gate size.")

        win_k = 0
        gran_k = 0
        # Determine the number of decimal places in gate_size if it is not an integer number of seconds.
        if not gate_size.total_seconds().is_integer():
            win_k = len(str(gate_size.total_seconds()).split(".")[-1]) + 1
        # Determine the number of decimal places in step if it is not an integer number of seconds.
        if not step.total_seconds().is_integer():
            gran_k = len(str(step.total_seconds()).split(".")[-1]) + 1
        # If there is any fractional part, scale the values to avoid floating point precision issues.
        if win_k or gran_k:
            k = 10 ** max(win_k, gran_k)
            win = gate_size.total_seconds() * k
            gran = step.total_seconds() * k
        else:
            win = gate_size.total_seconds()
            gran = step.total_seconds()

        # Check that the gate is evenly divisible by the step.
        if win % gran:
            raise CallGateValueError("gate must be divisible by frame step without remainder.")

        return gate_size, step

    @staticmethod
    def _validate_and_set_timezone(tz_name: str) -> Optional[ZoneInfo]:
        if tz_name is Sentinel or tz_name is None:
            return None
        return ZoneInfo(tz_name)

    def _validate_and_set_limits(self, gate_limit: Any, frame_limit: Any) -> tuple[int, int]:
        if not all(self._is_int(val) for val in (gate_limit, frame_limit)):
            raise CallGateTypeError("Limits must be integers.")
        if not all(val >= 0 for val in (gate_limit, frame_limit)):
            raise CallGateValueError("Limits must be positive integers or 0.")
        if 0 < gate_limit < frame_limit:
            raise CallGateValueError("Frame limit can not exceed gate limit if both of them are above 0.")
        return gate_limit, frame_limit

    @staticmethod
    def _validate_and_set_timestamp(timestamp: Any) -> Optional[datetime]:
        if timestamp is not None:
            if not isinstance(timestamp, str):
                raise CallGateTypeError(f"Timestamp must be an ISO string, received type: {type(timestamp)}.")
            try:
                if "Z" in timestamp:
                    timestamp = timestamp.replace("Z", "+00:00")
                return datetime.fromisoformat(timestamp)
            except ValueError as e:
                raise CallGateValueError("Timestamp must be an ISO string.") from e
        return None

    def _validate_data(self, data: Union[list[int], tuple[int, ...]]) -> None:
        if not isinstance(data, (list, tuple)):
            raise CallGateTypeError("Data must be a list or a tuple.")
        if not all(self._is_int(v) for v in data):
            raise CallGateTypeError("Data must be a list or a tuple of integers.")

    def __init__(
        self,
        name: str,
        gate_size: Union[timedelta, int, float],
        frame_step: Union[timedelta, int, float],
        *,
        gate_limit: int = 0,
        frame_limit: int = 0,
        timezone: str = Sentinel,
        storage: GateStorageModeType = GateStorageType.simple,
        _data: Optional[Union[list[int], tuple[int, ...]]] = None,
        _current_dt: Optional[str] = None,
        **kwargs: dict[str, Any],
    ) -> None:
        manager = get_global_manager()
        self._lock = manager.Lock()
        self._rlock = manager.RLock()
        self._alock: Optional[asyncio.Lock] = None
        self._executor: Optional[ThreadPoolExecutor] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._name = name
        self._timezone: Optional[ZoneInfo] = self._validate_and_set_timezone(timezone)
        self._gate_size, self._frame_step = self._validate_and_set_gate_and_granularity(gate_size, frame_step)
        self._gate_limit, self._frame_limit = self._validate_and_set_limits(gate_limit, frame_limit)
        self._frames: int = int(self._gate_size // self._frame_step)
        self._kwargs = kwargs

        storage_err = ValueError("Invalid `storage`: gate storage must be one of `GateStorageType` values.")
        if not isinstance(storage, (str, GateStorageType)):
            raise storage_err

        if isinstance(storage, str):
            try:
                storage = GateStorageType[storage]
            except KeyError as e:
                raise storage_err from e

        if storage == GateStorageType.simple:
            storage_type = SimpleStorage

        elif storage == GateStorageType.shared:
            storage_type = SharedMemoryStorage

        elif storage == GateStorageType.redis:
            if redis is Sentinel:  # no cov
                raise CallGateImportError(
                    "Package `redis` (`redis-py`) is not installed. Please, install it manually to use Redis storage "
                    "or set storage to `simple' or `shared`."
                )
            from call_gate.storages.redis import RedisStorage

            storage_type = RedisStorage

        else:  # no cov
            raise storage_err

        self._storage: GateStorageType = storage
        kw = {}
        if _data:
            self._validate_data(_data)
            kw.update({"data": _data})
        if kwargs:  # no cov
            kw.update(**kwargs)  # type: ignore[call-overload]
        self._data: BaseStorage = storage_type(name, self._frames, manager=manager, **kw)  # type: ignore[arg-type]

        # Initialize _current_dt: validate provided value first, then try to restore from storage
        if _current_dt is not None:
            self._current_dt: Optional[datetime] = self._validate_and_set_timestamp(_current_dt)
        else:
            # Try to restore timestamp from storage
            stored_timestamp = self._data.get_timestamp()
            self._current_dt = stored_timestamp

    def __del__(self) -> None:
        """Cleanup resources on deletion."""
        try:
            if hasattr(self, "_executor") and self._executor is not None:
                self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:  # noqa: S110
            pass  # Ignore errors during cleanup

    def as_dict(self) -> dict:
        """Serialize the gate to a dictionary.

        May be used for persisting the gate state.
        """
        with self._rlock:
            return {
                "name": self.name,
                "gate_size": self.gate_size.total_seconds(),
                "frame_step": self.frame_step.total_seconds(),
                "gate_limit": self.gate_limit,
                "frame_limit": self.frame_limit,
                "timezone": self.timezone.key if self.timezone else None,
                "storage": self.storage,
                "_data": self.data,
                "_current_dt": self._current_dt.isoformat() if self._current_dt else None,
                **self._kwargs,
            }

    def to_file(self, path: Union[str, Path]) -> None:
        """Save CallGate state to file.

        If path to file does not exit, it will be given a try to be created.

        :param path: path to file
        """
        if isinstance(path, str):
            path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            json.dump(self.as_dict(), file, indent=2)

    @classmethod
    def from_file(
        cls,
        path: Union[str, Path],
        *,
        storage: GateStorageModeType = Sentinel,
    ) -> "CallGate":
        """Restore the gate from file.

        Any supported type of storage can be indicated for a new gate,
        otherwise it will be restored from the metadata.

        :param path: path to file
        :param storage: storage type
        """
        if isinstance(path, str):
            path = Path(path)
        with path.open(mode="r", encoding="utf-8") as f:
            state = json.load(f)
            if storage is not Sentinel and storage != state["storage"]:
                state["storage"] = storage
            return cls(**state)

    def _current_step(self) -> datetime:
        current_time = datetime.now(self._timezone)
        remainder = current_time.timestamp() % self._frame_step.total_seconds()
        return current_time - timedelta(seconds=remainder)

    def _refresh_frames(self) -> None:
        current_step = self._current_step()
        if not self._current_dt:
            self._current_dt = current_step
            self._data.set_timestamp(current_step)
            return
        diff = int((current_step - self._current_dt) / self._frame_step)
        if diff >= self._frames:
            self.clear()
        elif diff > 0:
            self._data.slide(diff)
            self._current_dt = current_step
            self._data.set_timestamp(current_step)

    @dual
    def update(self, value: int = 1, throw: bool = False) -> None:
        """Update the counter in the current frame and gate sum.

        It is possible to update the gate with a custom **positive** value.

        Passing zero will do nothing.

        Passing a negative value may raise a ``CallGateOverflowError`` exception,
        because neither the gate sum nor the frame value can be negative.

        :param value: The value to add to the current frame value.
        :param throw: If True, the method will raise an exception if the limit is exceeded.
        """
        if not self._is_int(value):
            raise CallGateTypeError("Value must be an integer.")
        if value == 0:
            return  # return early as there's nothing to do
        if value > self.frame_limit > 0:
            raise FrameLimitError(f"The passed value exceeds the set frame limit: {value} > {self.frame_limit}", self)

        with self._rlock:
            self._refresh_frames()
            try:
                self._data.atomic_update(value, self._frame_limit, self._gate_limit)
            except Exception as e:
                if throw:
                    if isinstance(e, SpecialCallGateError):
                        raise e.__class__(e.message, self) from e
                    else:
                        raise e
                else:
                    while True:
                        self._refresh_frames()
                        try:
                            self._data.atomic_update(value, self._frame_limit, self._gate_limit)
                            break
                        except ThrottlingError:
                            time.sleep(self.frame_step.total_seconds())

    @property
    def name(self) -> str:
        """Get gate name."""
        return self._name

    @property
    def gate_size(self) -> timedelta:
        """Get the total gate size as a timedelta."""
        return self._gate_size

    @property
    def storage(self) -> str:
        """Get gate storage type."""
        return self._storage.name

    @property
    def data(self) -> list:
        """Get a copy of the data values."""
        with self._lock:
            return self._data.as_list()

    @property
    def state(self) -> State:
        """Get the current state of the storage."""
        return self._data.state

    @property
    def frame_step(self) -> timedelta:
        """Get the step of the gate frames as a timedelta."""
        return self._frame_step

    @property
    def frames(self) -> int:
        """Get the number of frames in the gate."""
        return self._frames

    @property
    def limits(self) -> CallGateLimits:
        """Get gate and frame limits in a tuple."""
        return CallGateLimits(gate_limit=self._gate_limit, frame_limit=self._frame_limit)

    @property
    def gate_limit(self) -> int:
        """Get the maximum limit of the gate."""
        return self._gate_limit

    @property
    def frame_limit(self) -> int:
        """Get the maximum value limit for each frame in the gate."""
        return self._frame_limit

    @property
    def timezone(self) -> Optional[ZoneInfo]:
        """Get the timezone used for datetime observing."""
        return self._timezone

    @property
    def current_dt(self) -> Optional[datetime]:
        """Get the current frame datetime."""
        return self._current_dt

    @property
    def sum(self) -> int:
        """Get the sum of all values in the gate."""
        with self._lock:
            return self._data.sum

    @property
    def current_frame(self) -> Frame:
        """Get time and value of the current frame."""
        with self._lock:
            current = self._current_dt if self._current_dt else self._current_step()
            return Frame(current, self._data[0])

    @property
    def last_frame(self) -> Frame:
        """Get time and value of the last frame."""
        with self._lock:
            current = self._current_dt if self._current_dt else self._current_step()
            return Frame(current - self._frame_step * (self._frames - 1), self._data[self._frames - 1])

    @dual
    def check_limits(self) -> None:
        """Check if the total and cell limits are satisfied.

        :raises ThrottlingError: Raised if either the `gate_limit` or `frame_limit` is exceeded.
        """
        sum_ = self.sum
        current_value = self.current_frame.value
        with self._lock:
            self._refresh_frames()
            if self._gate_limit and sum_ >= self._gate_limit:
                raise GateLimitError(f"Gate limit is reached: {self._gate_limit}", self)
            if self._frame_limit and current_value >= self._frame_limit:
                raise FrameLimitError(f"Frame limit is reached: {self._frame_limit}", self)

    @dual
    def clear(self) -> None:
        """Clean the gate (make it empty).

        Removes all counters and sets gate sum to zero.
        """
        with self._lock:
            self._data.clear()
            self._data.clear_timestamp()
            self._current_dt = None

    def __call__(self, value: int = 1, *, throw: bool = False) -> _CallGateWrapper:
        """Gate instance decorator for functions and coroutines.

        :param value: The value to add to the current frame value.
        :param throw: If True, the method will raise an exception if the limit is exceeded.
        """
        return _CallGateWrapper(self, value, throw)

    def __len__(self) -> int:
        """Get current number of the gate existing frames."""
        return self._frames

    def __repr__(self) -> str:
        """Gate representation."""
        d = self.as_dict()
        d.pop("_data")
        d.pop("_current_dt")
        return f"{self.__class__.__name__}({', '.join(f'{k}={v}' for k, v in d.items())})"

    def __str__(self) -> str:
        """Gate string representation."""
        return str(self.state)
