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

import inspect
import json
import logging
import time

from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union
from zoneinfo import ZoneInfo

from call_gate.errors import (
    CallGateImportError,
    CallGateRedisConfigurationError,
    CallGateTypeError,
    CallGateValueError,
    FrameLimitError,
    GateLimitError,
    SpecialCallGateError,
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

    from redis import Redis, RedisCluster

    from call_gate.storages.redis import RedisStorage
except ImportError:
    redis = Sentinel
    Redis = Sentinel
    RedisCluster = Sentinel
    RedisStorage = Sentinel

_DEFAULT_LOG_FORMAT = "%(levelname)s %(asctime)s %(name)s %(message)s"
_LOG_LEVEL_BY_NAME = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
}


class CallGate:
    """Thread-safe, process-safe, coroutine-safe distributed time-bound rate limit counter.

    The gate divides time into equal frames based on gate size and frame step parameters.
    Each frame tracks increments and decrements within its time period. Values in ``data[0]``
    are always bound to the current granular time frame step. Tracking timestamp may be bound
    to a personalized timezone.

    The gate maintains only values within its bounds, automatically removing old values when
    the gate is full and a new frame period starts.

    Frame values sum increases while the gate is not full. When full, the sum decreases on
    each slide (due to outdated frame removal) and increases again on each increment.

    If the gate was unused for a while and frames are outdated when a new increment occurs,
    outdated frames are replaced with the new period from the current moment up to the last
    valid timestamp. On increment, the gate always maintains frames from current moment back
    to history, ordered by granular frame step without gaps.

    When gate or frame limits are set and exceeded, ``GateLimitError`` or ``FrameLimitError``
    (derived from ``ThrottlingError``) will be raised, providing information about the
    exceeded limit type and value.

    The gate may raise custom exceptions derived from ``CallGateBaseError``, which also
    originate from Python native exceptions: ``ValueError``, ``TypeError``, ``ImportError``.

    **Storage Types:**

    - ``GateStorageType.simple`` (default) - stores data in ``collections.deque``
    - ``GateStorageType.shared`` - stores data in shared memory between processes and threads
    - ``GateStorageType.redis`` - stores data in Redis for distributed applications

    **Redis Storage:**

    Redis storage supports both single Redis instances and Redis clusters. For Redis storage,
    provide a pre-initialized Redis or RedisCluster client via the ``redis_client`` parameter.

    :param name: Gate name for identification.
    :param gate_size: Total gate size as timedelta or seconds.
    :param frame_step: Frame granularity as timedelta or seconds.
    :param gate_limit: Maximum sum across gate (0 = no limit).
    :param frame_limit: Maximum value per frame (0 = no limit).
    :param timezone: Timezone name for timestamp handling.
    :param storage: Storage type from GateStorageType.
    :param redis_client: Pre-initialized Redis/RedisCluster client for Redis storage
        (``decode_responses=True`` is required).
    :param log_level: Logging level (``str`` name or ``int`` constant). ``None`` (default) leaves
        the logger without a dedicated handler. Pass ``"INFO"``, ``logging.DEBUG``, etc. to attach
        a ``StreamHandler`` on this instance.
    :param log_format: ``logging.Formatter`` pattern when ``log_level`` is set.
    """

    @staticmethod
    def _is_int(value: Any) -> bool:
        return value is not None and not isinstance(value, bool) and isinstance(value, int)

    @staticmethod
    def _redis_client_has_decode_responses(redis_client: Union[Redis, RedisCluster]) -> bool:
        """Return True if the client's connection pool decodes responses to str."""
        if isinstance(redis_client, Redis):
            pool = getattr(redis_client, "connection_pool", None)
            if pool is not None:
                return bool(pool.connection_kwargs.get("decode_responses"))
            return False
        if isinstance(redis_client, RedisCluster):
            nodes_manager = getattr(redis_client, "nodes_manager", None)
            if nodes_manager is not None:
                for node in nodes_manager.nodes_cache.values():
                    conn = getattr(node, "redis_connection", None)
                    if conn is not None:
                        pool = getattr(conn, "connection_pool", None)
                        if pool is not None and pool.connection_kwargs.get("decode_responses"):
                            return True
            return False
        return False

    def _validate_redis_configuration(
        self, redis_client: Optional[Union[Redis, RedisCluster]], storage: GateStorageModeType
    ) -> None:
        """Validate Redis client configuration and perform connection test.

        :raises: CallGateRedisConfigurationError
        """
        if storage in (GateStorageType.redis, "redis") and redis_client is None:
            raise CallGateRedisConfigurationError(
                "Redis storage requires a pre-initialized `Redis` or `RedisCluster` client."
            )

        if redis_client is not None:
            if not isinstance(redis_client, (Redis, RedisCluster)):
                raise CallGateRedisConfigurationError(
                    "The 'redis_client' parameter must be a pre-initialized `Redis` or `RedisCluster` client. "
                    f"Received type: {type(redis_client)}."
                )

            try:
                redis_client.ping()
            except Exception as e:
                raise CallGateRedisConfigurationError(f"Failed to connect to Redis: {e}") from e

            if not self._redis_client_has_decode_responses(redis_client):
                raise CallGateRedisConfigurationError(
                    "Redis client must have decode_responses=True. "
                    "Pass decode_responses=True when creating the Redis or RedisCluster client."
                )

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
    def _setup_logger(name: str, log_level: Optional[Union[str, int]], log_format: str) -> None:
        """Configure ``CallGate.{name}`` when *log_level* is set (not stored on the instance)."""
        if log_level is None:
            return
        logger = logging.getLogger(f"CallGate.{name}")
        level = CallGate._normalize_log_level(log_level)
        logger.setLevel(level)
        handler = logging.StreamHandler()
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(log_format))
        logger.handlers.clear()
        logger.addHandler(handler)
        logger.propagate = False

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
        redis_client: Optional[Union[Redis, RedisCluster]] = None,
        redis_lock_timeout: int = 5,
        redis_lock_blocking_timeout: int = 5,
        log_level: Optional[Union[str, int]] = None,
        log_format: str = _DEFAULT_LOG_FORMAT,
        _data: Optional[Union[list[int], tuple[int, ...]]] = None,
        _current_dt: Optional[str] = None,
    ) -> None:
        self._setup_logger(name, log_level, log_format)
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

        storage_kw: dict[str, Any] = {}

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
            # Pass manager to Simple storage
            storage_kw["manager"] = manager

        elif storage == GateStorageType.shared:
            storage_type = SharedMemoryStorage
            # Pass manager to Shared storage
            storage_kw["manager"] = manager

        elif storage == GateStorageType.redis:
            if redis is Sentinel:  # no cov
                raise CallGateImportError(
                    "Package `redis` (`redis-py`) is not installed. Please, install it manually to use Redis storage "
                    "or set storage to `simple' or `shared`."
                )
            storage_type = RedisStorage
            self._validate_redis_configuration(redis_client, storage)
            # Add redis_client for Redis storage (Redis uses its own locks, not manager)
            if redis_client is not None:
                storage_kw["client"] = redis_client
                storage_kw["lock_timeout"] = redis_lock_timeout
                storage_kw["lock_blocking_timeout"] = redis_lock_blocking_timeout

        else:  # no cov
            raise storage_err

        self._storage: GateStorageType = storage

        if _data:
            self._validate_data(_data)
            storage_kw.update({"data": _data})

        self._data: BaseStorage = storage_type(
            name,
            self._frames,
            **storage_kw,  # type: ignore[arg-type]
        )

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

    @staticmethod
    def _validate_gate_limit_max_wait_frames(gate_limit_max_wait_frames: Any) -> int:
        if not CallGate._is_int(gate_limit_max_wait_frames):
            raise CallGateTypeError("gate_limit_max_wait_frames must be an integer.")
        if gate_limit_max_wait_frames < 0:
            raise CallGateValueError("gate_limit_max_wait_frames must be >= 0.")
        return gate_limit_max_wait_frames

    @staticmethod
    def _normalize_log_level(level: Union[str, int]) -> int:
        if isinstance(level, int):
            return level
        if isinstance(level, str):
            normalized = _LOG_LEVEL_BY_NAME.get(level.upper())
            if normalized is not None:
                return normalized
        raise CallGateValueError(f"Invalid log level: {level!r}.")

    @property
    def _logger(self) -> logging.Logger:
        return logging.getLogger(f"CallGate.{self._name}")

    def _ensure_process_locks(self) -> None:
        """Create manager locks if missing (after unpickling; not created in ``__setstate__``)."""
        if self._lock is not None and self._rlock is not None:
            return
        manager = get_global_manager()
        self._lock = manager.Lock()
        self._rlock = manager.RLock()

    def _data_unlocked(self) -> list:
        return self._data.as_list()

    def as_dict(self) -> dict:
        """Serialize the gate to a dictionary.

        May be used for persisting the gate state.
        """
        self._ensure_process_locks()
        with self._rlock:
            with self._lock:
                return {
                    "name": self._name,
                    "gate_size": self._gate_size.total_seconds(),
                    "frame_step": self._frame_step.total_seconds(),
                    "gate_limit": self._gate_limit,
                    "frame_limit": self._frame_limit,
                    "timezone": self._timezone.key if self._timezone else None,
                    "storage": self._storage.name,
                    "_data": self._data_unlocked(),
                    "_current_dt": self._current_dt.isoformat() if self._current_dt else None,
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
        redis_client: Optional[Union[Redis, RedisCluster]] = None,
    ) -> "CallGate":
        """Restore the gate from file.

        Any supported type of storage can be indicated for a new gate,
        otherwise it will be restored from the metadata.

        :param path: path to file
        :param storage: storage type
        :param redis_client: pre-initialized Redis/RedisCluster client for Redis storage
        """
        sig = inspect.signature(cls.__init__)
        allowed_params = set(sig.parameters.keys()) - {"self", "redis_client"}

        if isinstance(path, str):
            path = Path(path)

        with path.open(mode="r", encoding="utf-8") as f:
            state = json.load(f)

        if storage is not Sentinel and storage != state["storage"]:
            state["storage"] = storage

        filtered_params = {k: v for k, v in state.items() if k in allowed_params}

        return cls(**filtered_params, redis_client=redis_client)

    def _current_step(self) -> datetime:
        current_time = datetime.now(self._timezone)
        remainder = current_time.timestamp() % self._frame_step.total_seconds()
        return current_time - timedelta(seconds=remainder)

    def _align_to_frame_step(self, dt: datetime) -> datetime:
        """Floor *dt* to the start of its frame step (same grid as ``_current_step``)."""
        remainder = dt.timestamp() % self._frame_step.total_seconds()
        return dt - timedelta(seconds=remainder)

    def _sum_unlocked(self) -> int:
        return self._data.sum

    def _current_frame_unlocked(self) -> Frame:
        current = self._current_dt if self._current_dt else self._current_step()
        return Frame(current, self._data[0])

    def _last_frame_unlocked(self) -> Frame:
        current = self._current_dt if self._current_dt else self._current_step()
        return Frame(
            current - self._frame_step * (self._frames - 1),
            self._data[self._frames - 1],
        )

    def _clear_unlocked(self) -> None:
        self._data.clear()
        self._data.clear_timestamp()
        self._current_dt = None

    def _sync_current_dt_from_storage(self) -> None:
        """Align local window position with storage timestamp."""
        if isinstance(self._data, SimpleStorage):
            return
        stored = self._data.get_timestamp()
        if stored is None:
            return
        stored = self._align_to_frame_step(stored)
        if self._current_dt is not None:
            self._current_dt = max(self._current_dt, stored)
        else:
            self._current_dt = stored

    def _refresh_frames_unlocked(self) -> None:
        """Shift the sliding window to match the current time step.

        For Redis storage, local ``_current_dt`` is synced from the storage
        timestamp before computing ``diff``, so multiple processes/pods sharing
        the same gate cannot double-slide and lose ``sum``.
        """
        current_step = self._current_step()
        if not self._current_dt:
            self._current_dt = current_step
            self._data.set_timestamp(current_step)
            return
        self._sync_current_dt_from_storage()
        diff = int((current_step - self._current_dt) / self._frame_step)
        if diff >= self._frames:
            self._logger.info(
                "Clearing sliding window (diff=%s, frames=%s)",
                diff,
                self._frames,
            )
            self._clear_unlocked()
        elif diff > 0:
            self._logger.debug("Sliding window by %s frame(s)", diff)
            self._data.slide(diff)
            self._current_dt = current_step
            self._data.set_timestamp(current_step)

    def _log_update_succeeded(self, value: int, waits_used: int = 0) -> None:
        sum_ = self.sum
        if waits_used:
            self._logger.info(
                "Update succeeded after %s wait(s), value=%s, sum=%s",
                waits_used,
                value,
                sum_,
            )
        else:
            self._logger.info("Update succeeded, value=%s, sum=%s", value, sum_)

    def _effective_max_wait_frames(self, gate_limit_max_wait_frames: int) -> int:
        if gate_limit_max_wait_frames > 0:
            return gate_limit_max_wait_frames
        return self._frames

    def _update_blocking_unlocked(self, value: int, gate_limit_max_wait_frames: int) -> None:
        self._ensure_process_locks()
        waits_left = self._effective_max_wait_frames(gate_limit_max_wait_frames)
        initial_waits = waits_left
        while True:
            with self._lock:
                self._refresh_frames_unlocked()
            try:
                self._data.atomic_update(value, self._frame_limit, self._gate_limit)
                self._log_update_succeeded(value, initial_waits - waits_left)
                return
            except FrameLimitError:
                if waits_left <= 0:
                    self._logger.warning(
                        "Frame limit still exceeded after %s wait(s), raising",
                        initial_waits,
                    )
                    raise FrameLimitError("Frame limit exceeded", self) from None
                self._logger.debug(
                    "Frame limit reached, sleeping one frame step (waits_left=%s, value=%s)",
                    waits_left,
                    value,
                )
                waits_left -= 1
                time.sleep(self.frame_step.total_seconds())
            except GateLimitError:
                if waits_left <= 0:
                    self._logger.warning(
                        "Gate limit still exceeded after %s wait(s), raising",
                        initial_waits,
                    )
                    raise GateLimitError("Gate limit exceeded", self) from None
                self._logger.debug(
                    "Gate limit reached, sleeping one frame step (waits_left=%s, value=%s)",
                    waits_left,
                    value,
                )
                waits_left -= 1
                time.sleep(self.frame_step.total_seconds())

    def _refresh_frames(self) -> None:
        self._ensure_process_locks()
        with self._lock:
            self._refresh_frames_unlocked()

    def _check_limits_unlocked(self) -> None:
        self._refresh_frames_unlocked()
        sum_ = self._sum_unlocked()
        current_value = self._current_frame_unlocked().value
        if self._gate_limit and sum_ >= self._gate_limit:
            raise GateLimitError(
                f"Gate limit is reached: {self._gate_limit}",
                self,
            )
        if self._frame_limit and current_value >= self._frame_limit:
            raise FrameLimitError(
                f"Frame limit is reached: {self._frame_limit}",
                self,
            )

    @dual
    def update(self, value: int = 1, throw: bool = False, gate_limit_max_wait_frames: int = 0) -> None:
        """Update the counter in the current frame and gate sum.

        It is possible to update the gate with a custom **positive** value.

        Passing zero will do nothing.

        Passing a negative value may raise a ``CallGateOverflowError`` exception,
        because neither the gate sum nor the frame value can be negative.

        :param value: The value to add to the current frame value.
        :param throw: If True, raise ``FrameLimitError`` or ``GateLimitError`` as soon as the
            limit is exceeded. If False, sleep ``frame_step`` and refresh the window until the
            increment can be applied.
        :param gate_limit_max_wait_frames: When ``throw=False``, how many **frames** (``frame_step``
            periods) the call may wait through on limit errors before raising. ``0`` (default) means
            all ``frames`` in the gate — one full ``gate_size``. ``N > 0`` — at most ``N`` frames
            (~``N × frame_step`` wall time). Not a second count; not ``gate_limit``.
        """
        if not self._is_int(value):
            raise CallGateTypeError("Value must be an integer.")
        if value == 0:
            return  # return early as there's nothing to do
        if value > self.frame_limit > 0:
            raise FrameLimitError(f"The passed value exceeds the set frame limit: {value} > {self.frame_limit}", self)
        if value > self._gate_limit > 0:
            raise GateLimitError(f"The passed value exceeds the set gate limit: {value} > {self._gate_limit}", self)
        max_wait = self._validate_gate_limit_max_wait_frames(gate_limit_max_wait_frames)

        self._ensure_process_locks()
        with self._rlock:
            if throw:
                with self._lock:
                    self._refresh_frames_unlocked()
                try:
                    self._data.atomic_update(value, self._frame_limit, self._gate_limit)
                except Exception as e:
                    if isinstance(e, SpecialCallGateError):
                        raise e.__class__(e.message, self) from e
                    raise e
                self._log_update_succeeded(value)
            else:
                self._update_blocking_unlocked(value, max_wait)

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
        self._ensure_process_locks()
        with self._lock:
            return self._data_unlocked()

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
        self._ensure_process_locks()
        with self._lock:
            return self._sum_unlocked()

    @property
    def current_frame(self) -> Frame:
        """Get time and value of the current frame."""
        self._ensure_process_locks()
        with self._lock:
            return self._current_frame_unlocked()

    @property
    def last_frame(self) -> Frame:
        """Get time and value of the last frame."""
        self._ensure_process_locks()
        with self._lock:
            return self._last_frame_unlocked()

    @dual
    def check_limits(self) -> None:
        """Check if the total and cell limits are satisfied.

        :raises ThrottlingError: Raised if either the `gate_limit` or `frame_limit` is exceeded.
        """
        self._ensure_process_locks()
        with self._rlock:
            with self._lock:
                self._check_limits_unlocked()

    @dual
    def clear(self) -> None:
        """Clean the gate (make it empty).

        Removes all counters and sets gate sum to zero.
        """
        self._ensure_process_locks()
        with self._rlock:
            with self._lock:
                self._clear_unlocked()

    def __call__(
        self,
        value: int = 1,
        *,
        throw: bool = False,
        gate_limit_max_wait_frames: int = 0,
    ) -> _CallGateWrapper:
        """Gate instance decorator for functions and coroutines.

        Equivalent to ``update(value, throw, gate_limit_max_wait_frames)`` on each use.

        :param value: The value to add to the current frame value.
        :param throw: If True, raise when a limit is exceeded; see ``update``.
        :param gate_limit_max_wait_frames: Max **frames** to wait through on limit when
            ``throw=False``; see ``update``.
        """
        max_wait = self._validate_gate_limit_max_wait_frames(gate_limit_max_wait_frames)
        return _CallGateWrapper(self, value, throw, max_wait)

    def __len__(self) -> int:
        """Get current number of the gate existing frames."""
        return self._frames

    def __getstate__(self) -> dict[str, Any]:
        state = self.__dict__.copy()
        for key in ("_lock", "_rlock", "_alock", "_executor", "_loop"):
            state.pop(key, None)
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update(state)
        self._lock = None
        self._rlock = None
        self._alock = None
        self._executor = None
        self._loop = None

    def __repr__(self) -> str:
        """Gate representation."""
        d = self.as_dict()
        d.pop("_data")
        d.pop("_current_dt")
        return f"{self.__class__.__name__}({', '.join(f'{k}={v}' for k, v in d.items())})"

    def __str__(self) -> str:
        """Gate string representation."""
        return str(self.state)
