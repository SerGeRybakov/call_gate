import time
from asyncio import iscoroutinefunction
from datetime import datetime, timedelta
from functools import wraps
from multiprocessing import RLock, Lock
from typing import Any, Optional, Union, Type
from zoneinfo import ZoneInfo

from sliding_window import ThrottlingError
from sliding_window.base.base_storage import BaseWindowStorage
from sliding_window.errors import (
    FrameLimitError,
    SlidingWindowImportError,
    SlidingWindowTypeError,
    SlidingWindowValueError,
    WindowLimitError,
)
from sliding_window.storages.simple import SimpleWindowStorage
from sliding_window.typings import Frame, KWType, Sentinel, WindowStorageMode, WindowStorageModeType

try:
    import numpy as np
except ImportError:
    np = Sentinel

try:
    import redis
except ImportError:
    redis = Sentinel


class SlidingWindow:
    """Sliding window time-bound counter.

    Sliding window is divided into equal frames basing on the window size and frame step.
    Each frame is bound to the frame_step set frame step and keeps track of increments and decrements
    within a time period equal to the frame step. Values in the ``data[0]`` are always bound
    to the current granular time frame step. Tracking timestamp may be bound to a personalized timezone.

    The window keeps only those values which are within the window bounds. The old values are removed
    automatically when the window is full and the new frame period started.

    The sum of the frames values increases while the window is not full. When it's full, the sum will
    decrease on each slide (due to erasing of the outdated frames) and increase again on each increment.

    If the window was not used for a while and some (or all) frames are outdated and a new increment
    is made, the outdated frames will be replaced with the new period from the current moment
    up to the last valid timestamp (if there is one). In other words, on increment the window always
    keeps frames from the current moment back to history, ordered by granular frame step without any gaps.

    If any of window or frame limit is set and  any of these limits are exceeded, ``WindowLimitError``
    or ``FrameLimitError`` (derived from ``ThrottlingError``) will be thrown.
    The error provides the information of the exceeded limit type and its value.

    Also, the window may throw its own exceptions derived from ``SlidingWindowBaseError``. Each of them
    also originates from Python typical native exceptions: ``ValueError``, ``TypeError``, ``ImportError``.

    The window has 3 types of data storage:
        - ``WindowStorageMode.simple`` (default) - stores data in a ``collections.deque``.

        - ``WindowStorageMode.shared`` (requires ``numpy``) - stores data in a NumPy array attached to
        a ``multiprocessing.SharedMemory`` buffer that is shared between processes and threads started
        from one parent process/thread. Why numpy? Benchmarks of 10**6 (1 million) elements array write/read:
            1) numpy:           Write: 0.001528s, Read: 0.001265s
            2) array.array:     Write: 0.003562s, Read: 0.001293s
            3) cython:          Write: 0.067095s, Read: 0.080463s


        - ``WindowStorageMode.redis`` (requires ``redis`` (``redis-py``)- stores data in Redis,
          what provides a distributed storage between multiple processes, servers and Docker containers.

    Window constructor accepts ``**kwargs`` for ``WindowStorageMode.redis`` storage. The parameters described
    at https://redis.readthedocs.io/en/latest/connections.html for ``redis.Redis`` object can be passed
    as keyword arguments. Redis URL is not supported. If not provided, the Window will use the default
    connection parameters, except the ``db``, which is set to ``15``.

    :param name: Window name
    :param window_size: The total size of the window (as a timedelta or number of seconds).
    :param frame_step: The granularity of each frame in the window (either as a timedelta or seconds).
    :param window_limit: Maximum allowed sum of values across the window, default is ``0`` (no limit).
    :param frame_limit: Maximum allowed value per frame in the window, default is ``0`` (no limit).
    :param timezone: Timezone name ("Europe/Rome") for handling frames timestamp, default is ``UTC``.
    :param storage: Type of data storage: one of WindowStorageMode keys, default is ``WindowStorageMode.simple``.
    :param kwargs: Special parameters for storage.
    """

    @staticmethod
    def _is_int(value: Any) -> bool:
        return value is not None and not isinstance(value, bool) and isinstance(value, int)

    @staticmethod
    def _validate_and_set_window_and_granularity(window_size: Any, step: Any) -> tuple[timedelta, timedelta]:
        # If window_size is an int or float, convert it to a timedelta using seconds.
        if isinstance(window_size, (int, float)):
            window_size = timedelta(seconds=window_size)
        # Similarly, if step is an int or float, convert it to a timedelta using seconds.
        if isinstance(step, (int, float)):
            step = timedelta(seconds=step)
        # Check that the step is less than the window size.
        if step >= window_size:
            raise SlidingWindowValueError("The frame step must be less than the window size.")

        win_k = 0
        gran_k = 0
        # Determine the number of decimal places in window_size if it is not an integer number of seconds.
        if not window_size.total_seconds().is_integer():
            win_k = len(str(window_size.total_seconds()).split(".")[-1]) + 1
        # Determine the number of decimal places in step if it is not an integer number of seconds.
        if not step.total_seconds().is_integer():
            gran_k = len(str(step.total_seconds()).split(".")[-1]) + 1
        # If there is any fractional part, scale the values to avoid floating point precision issues.
        if win_k or gran_k:
            k = 10 ** max(win_k, gran_k)
            win = window_size.total_seconds() * k
            gran = step.total_seconds() * k
        else:
            win = window_size.total_seconds()
            gran = step.total_seconds()

        # Check that the window is evenly divisible by the step.
        if win % gran:
            raise SlidingWindowValueError("Window must be divisible by frame step without remainder.")

        return window_size, step

    @staticmethod
    def _validate_and_set_timezone(timezone: Any) -> ZoneInfo:
        return ZoneInfo(timezone)

    def _validate_and_set_limits(self, window_limit: Any, frame_limit: Any) -> tuple[int, int]:
        if not all(self._is_int(val) for val in (window_limit, frame_limit)):
            raise SlidingWindowTypeError("Limits must be integers.")
        if not all(val >= 0 for val in (window_limit, frame_limit)):
            raise SlidingWindowValueError("Limits must be positive integers or 0.")
        if 0 < window_limit < frame_limit:
            raise SlidingWindowValueError("Frame limit can not exceed window limit if both of them are above 0.")
        return window_limit, frame_limit

    @staticmethod
    def _validate_and_set_timestamp(timestamp: Any) -> Optional[datetime]:
        if timestamp is not None:
            if not isinstance(timestamp, str):
                raise SlidingWindowTypeError(f"Timestamp must be an ISO string, received type: {type(timestamp)}.")
            try:
                if "Z" in timestamp:
                    timestamp = timestamp.replace("Z", "+00:00")
                return datetime.fromisoformat(timestamp)
            except ValueError:
                raise SlidingWindowValueError("Timestamp must be an ISO string.")
        return None

    def __init__(
            self,
            name: str,
            window_size: Union[timedelta, int, float],
            frame_step: Union[timedelta, int, float],
            *,
            window_limit: int = 0,
            frame_limit: int = 0,
            timezone: str = "UTC",
            storage: WindowStorageModeType = WindowStorageMode.simple,
            _data: Optional[Union[list[int], tuple[int, ...]]] = None,
            _current_dt: Optional[str] = None,
            **kwargs: KWType,
    ) -> None:
        self._lock = Lock()
        self._rlock = RLock()
        self._name = name
        self._timezone: ZoneInfo = self._validate_and_set_timezone(timezone)
        self._window_size, self._frame_step = self._validate_and_set_window_and_granularity(window_size, frame_step)
        self._window_limit, self._frame_limit = self._validate_and_set_limits(window_limit, frame_limit)
        self._frames: int = int(self._window_size // self._frame_step)
        self._current_dt: datetime = self._validate_and_set_timestamp(_current_dt)
        self._kwargs = kwargs

        storage_err = ValueError("Invalid `storage`: window storage storage must be one of `WindowStorageMode` values.")
        if not isinstance(storage, (str, WindowStorageMode)):
            raise storage_err

        if isinstance(storage, str):
            try:
                storage = WindowStorageMode[storage]
            except KeyError:
                raise storage_err

        if storage == WindowStorageMode.simple:
            storage_type = SimpleWindowStorage

        elif storage == WindowStorageMode.shared:
            if np is Sentinel:
                raise SlidingWindowImportError(
                    "Package `numpy` is not installed. Please, install it manually to use big numbers in shared memory"
                    "or set storage to `simple' or `shared`."
                )
            from sliding_window.storages.shared import SharedMemoryWindowStorage
            storage_type = SharedMemoryWindowStorage

        elif storage == WindowStorageMode.redis:
            if redis is Sentinel:
                raise SlidingWindowImportError(
                    "Package `redis` (`redis-py`) is not installed. Please, install it manually to use Redis storage "
                    "or set storage to `simple' or `shared`."
                )
            from sliding_window.storages.redis import RedisWindowStorage
            storage_type = RedisWindowStorage

        else:
            raise storage_err

        self._storage: WindowStorageMode = storage
        with self._lock:
            kw = {"name": name, "capacity": self._frames}
            if _data:
                kw.update({"data": _data})
            if kwargs:
                kw.update(kwargs)
            self._data: BaseWindowStorage = storage_type(**kw)

    def _current_step(self) -> datetime:
        current_time = datetime.now(self._timezone)
        remainder = current_time.timestamp() % self._frame_step.total_seconds()
        return current_time - timedelta(seconds=remainder)

    def _refresh_frames(self) -> None:
        current_step = self._current_step()
        if not self._current_dt:
            self._current_dt = current_step
            return
        diff = int((current_step - self._current_dt) / self._frame_step)
        if diff >= self._frames:
            self.clean()
        elif diff > 0:
            self._data.slide(diff)
            self._current_dt = current_step

    @property
    def name(self) -> str:
        """Get window name."""
        return self._name

    @property
    def window_size(self) -> timedelta:
        """Get the total window size as a timedelta."""
        return self._window_size

    @property
    def storage(self) -> str:
        """Get window storage type."""
        return self._storage.name

    @property
    def data(self) -> list:
        """Get a copy of the data values."""
        with self._lock:
            return self._data.as_list()

    @property
    def frame_step(self) -> timedelta:
        """Get the step of the window frames as a timedelta."""
        return self._frame_step

    @property
    def frames(self) -> int:
        """Get the number of frames in the window."""
        return self._frames

    @property
    def window_limit(self) -> int:
        """Get the maximum limit of the window."""
        return self._window_limit

    @property
    def frame_limit(self) -> int:
        """Get the maximum value limit for each frame in the window."""
        return self._frame_limit

    @property
    def timezone(self) -> ZoneInfo:
        """Get the timezone used for datetime observing."""
        return self._timezone

    @property
    def current_dt(self) -> Optional[datetime]:
        """Get the current frame datetime."""
        return self._current_dt

    @property
    def sum(self) -> int:
        """Get the sum of all values in the window."""
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

    def check_limits(self) -> None:
        """Check if the total and cell limits are satisfied.

        :raises ThrottlingError: Raised if either the `window_limit` or `frame_limit` is exceeded.
        """
        sum_ = self.sum
        current_value = self.current_frame.value
        with self._lock:
            self._refresh_frames()
            if self._frame_limit and current_value >= self._frame_limit:
                raise FrameLimitError(f"Frame limit is reached: {self._frame_limit}", self)
            if self._window_limit and sum_ >= self._window_limit:
                raise WindowLimitError(f"Window limit is reached: {self._window_limit}", self)

    def inc(self, value: int = 1, throw: bool = True) -> None:
        """Увеличивает счётчик в текущем кадре."""
        if not self._is_int(value):
            raise SlidingWindowTypeError("Value must be an integer.")
        if value == 0:
            return  # return early as there's nothing to do

        with self._rlock:
            self._refresh_frames()
            try:
                self._data.atomic_update(value, self._frame_limit, self._window_limit)
            except Exception as e:
                if throw:
                    if isinstance(e, ThrottlingError):
                        raise e.__class__(e.message, self) from e
                    else:
                        raise e
                else:
                    while True:
                        time.sleep(self.frame_step.total_seconds())
                        self._refresh_frames()
                        try:
                            self._data.atomic_update(value, self._frame_limit, self._window_limit)
                            break
                        except Exception:
                            continue

    def clean(self) -> None:
        """Clean the window (make it empty).

        Removes all counters and sets window sum to zero.
        """
        with self._lock:
            self._data.clear()
            self._current_dt = None

    def as_dict(self) -> dict:
        """Serialize the window to a dictionary.

        May be used for persisting the window state.
        """
        with self._rlock:
            return {
                "name": self.name,
                "window_size": self.window_size.total_seconds(),
                "frame_step": self.frame_step.total_seconds(),
                "window_limit": self.window_limit,
                "frame_limit": self.frame_limit,
                "timezone": self.timezone.key,
                "storage": self.storage,
                "_data": self.data,
                "_current_dt": self._current_dt.isoformat() if self._current_dt else None,
                **self._kwargs
            }

    def __call__(self, *args, **kwargs):
        """Window instance decorator for functions and coroutines."""

        def decorator(func):
            @wraps(func)
            async def awrapper(*args, **kwargs): ...

            @wraps(func)
            def wrapper(*args, **kwargs): ...

            if iscoroutinefunction(func):
                return awrapper
            return wrapper

        return decorator

    def __repr__(self) -> str:
        d = self.as_dict()
        d.pop("_data")
        d.pop("_current_dt")
        return f"{self.__class__.__name__}({', '.join(f'{k}={v}' for k, v in d.items())})"

    def close(self):
        self._data.close()

    def __getstate__(self):
        return self.as_dict()

    def __setstate__(self, state):
        # Восстанавливаем основные параметры
        self._name = state["name"]
        self._window_size = timedelta(seconds=state["window_size"])
        self._frame_step = timedelta(seconds=state["frame_step"])
        self._window_limit = state["window_limit"]
        self._frame_limit = state["frame_limit"]
        self._timezone = ZoneInfo(state["timezone"])
        self._storage = WindowStorageMode[state["storage"]]
        self._frames = int(self._window_size // self._frame_step)
        self._current_dt = (
            datetime.fromisoformat(state["_current_dt"]) if state["_current_dt"] else None
        )
        # Остальные дополнительные параметры
        self._kwargs = {
            k: v
            for k, v in state.items()
            if k
               not in (
                   "name",
                   "window_size",
                   "frame_step",
                   "window_limit",
                   "frame_limit",
                   "timezone",
                   "storage",
                   "_data",
                   "_current_dt",
               )
        }
        # Создаем блокировку заново (она не может быть запиклена)
        self._lock = RLock()

        # Восстанавливаем хранилище данных в зависимости от режима.
        if self._storage == WindowStorageMode.simple:
            storage = SimpleWindowStorage
        elif self._storage == WindowStorageMode.shared:
            from sliding_window.storages.shared import SharedMemoryWindowStorage
            storage = SharedMemoryWindowStorage
        elif self._storage == WindowStorageMode.redis:
            from sliding_window.storages.redis import RedisWindowStorage
            storage = RedisWindowStorage
        else:
            raise ValueError("Invalid storage storage during unpickling.")

        # Вызовем конструктор хранилища, передав сохранённое состояние данных.
        # Обратите внимание, что в конструкторе ожидается параметр 'data' вместо '_data'.
        self._data = storage(
            name=self._name,
            capacity=self._frames,
            data=state["_data"],
            **self._kwargs,
        )

    def __reduce__(self):
        # Метод __reduce__ возвращает кортеж: (callable, args, state)
        return (
            self.__class__,
            (self._name, self._window_size, self._frame_step),
            self.__getstate__(),
        )

    def __len__(self) -> int:
        """Current number of the sliding window existing frames."""
        return self._frames

    def __bool__(self) -> bool:
        """Check if the window is empty (full of zeros) or not?"""
        return bool(self._data)

    def __enter__(self, *args, **kwargs) -> None:
        pass

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    async def __aenter__(self, *args, **kwargs):
        pass

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
