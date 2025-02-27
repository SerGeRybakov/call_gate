"""
Redis-based window storage.

This module contains a window storage implementation using Redis as the storage engine.

The storage is suitable for distributed applications. The storage uses a Redis list to store
the window values. The Redis list is divided into frames which are accessed by the index of
the frame.

The storage is thread-safe and process-safe for multiple readers and writers.

The storage supports persistence of the window values. When the application is restarted,
the window values are not lost.
"""

import time
import uuid

from threading import RLock, get_ident
from types import TracebackType
from typing import Any, Optional

from redis import Redis, ResponseError
from typing_extensions import Unpack

from sliding_window import FrameLimitError, WindowLimitError
from sliding_window.errors import FrameOverflowError, WindowOverflowError
from sliding_window.storages.base_storage import BaseWindowStorage, _mute
from sliding_window.typings import WindowState


class RedisReentrantLock:
    """Implements a reentrant (recursive) distributed lock based on Redis.

    :param client: Redis connection instance.
    :param name: Unique lock name.
    :param timeout: Lock lifespan in seconds.
    """

    def __init__(self, client: Redis, name: str, timeout: int = 1) -> None:
        self.client = client
        self.lock_key = f"{name}:global_lock"
        self.owner_key = f"{name}:lock_owner"
        self.count_key = f"{name}:lock_count"
        self.owner = f"{get_ident()}:{uuid.uuid4()}"
        self.timeout = timeout

    def __enter__(self) -> "RedisReentrantLock":
        while True:
            current_owner = self.client.get(self.owner_key)
            # If the lock is already acquired by the current owner, just increment the counter and extend the TTL.
            if current_owner and current_owner.decode() == self.owner:
                self.client.hincrby(self.count_key, self.owner, 1)
                self.client.expire(self.lock_key, self.timeout)
                self.client.expire(self.owner_key, self.timeout)
                break
            # Try to set the lock atomically
            if self.client.set(self.lock_key, "1", nx=True, ex=self.timeout):
                # Lock acquired successfully - set the owner and start the counter at 1
                self.client.set(self.owner_key, self.owner, ex=self.timeout)
                self.client.hset(self.count_key, self.owner, "1")
                break
            else:
                time.sleep(0.01)  # A small delay to avoid busy-wait
        return self

    def __exit__(
        self, exc_type: Optional[type[Exception]], exc_val: Optional[Exception], exc_tb: Optional[TracebackType]
    ) -> None:
        count: int = self.client.hincrby(self.count_key, self.owner, -1)
        if count <= 0:
            # If the counter reaches zero - delete all related keys
            self.client.delete(self.lock_key, self.owner_key, self.count_key)
        else:
            # If there are still nested calls - extend the TTL
            self.client.expire(self.lock_key, self.timeout)
            self.client.expire(self.owner_key, self.timeout)


class RedisWindowStorage(BaseWindowStorage):
    """Redis-based window storage.

    This module contains a window storage implementation using Redis as the storage engine.

    The storage is suitable for distributed applications. The storage uses a Redis list to store
    the window values. The Redis list is divided into frames which are accessed by the index of
    the frame.

    The storage is thread-safe and process-safe for multiple readers and writers.

    The storage supports persistence of the window values. When the application is restarted,
    the window values are not lost.
    :param name: The name of the window.
    :param capacity: The maximum number of values that the window can store.
    :param data: Optional initial data for the window.
    """

    _data: str  # Redis key for our list
    _sum: str  # Redis key for the sum of the window

    def __init__(
        self, name: str, capacity: int, *, data: Optional[list[int]] = None, **kwargs: Unpack[dict[str, Any]]
    ) -> None:
        """
        Initialize the RedisWindowStorage.

        :param name: Name of the sliding window.
        :param capacity: The capacity of the window.
        :param data: Optional initial list of integers.
        :param kwargs: Additional keyword arguments for Redis connection.
        """
        super().__init__(name, capacity)
        if "db" not in kwargs:
            kwargs["db"] = 15
        self._data = self.name  # key for list
        self._sum = f"{self.name}:sum"  # key for the sum
        self._shm: Redis = Redis(**kwargs)
        self._lock = self._shm.lock(f"{self.name}:lock", blocking=True, timeout=1, blocking_timeout=1)
        self._rlock = RLock()
        self._redis_global_lock = RedisReentrantLock(self._shm, self.name)

        # Lua script for initialization: sets the list and computes the sum.
        lua_script = """
        local key_list = KEYS[1]
        local key_sum = KEYS[2]
        local capacity = tonumber(ARGV[1])
        local provided = #ARGV - 1
        local data = {}
        local total = 0
        if provided > 0 then
            for i = 2, math.min(#ARGV, capacity + 1) do
                table.insert(data, ARGV[i])
                total = total + tonumber(ARGV[i])
            end
            if provided < capacity then
                local pad = capacity - provided
                local padded = {}
                for i = 1, pad do
                    table.insert(padded, "0")
                end
                for i = 1, #data do
                    table.insert(padded, data[i])
                end
                data = padded
            end
        else
            for i = 1, capacity do
                table.insert(data, "0")
            end
            total = 0
        end
        redis.call("DEL", key_list)
        redis.call("DEL", key_sum)
        for i = 1, #data do
            redis.call("RPUSH", key_list, data[i])
        end
        redis.call("SET", key_sum, total)
        return total
        """
        with self._redis_global_lock:
            with self._lock:
                if data is not None:
                    args = [str(self.capacity)] + [str(x) for x in data]
                else:
                    args = [str(self.capacity)]
                self._shm.eval(lua_script, 2, self._data, self._sum, *args)

    @property
    def sum(self) -> int:
        """Property to get the current sum of the window from Redis.

        :return: The sum of the window.
        """
        with self._redis_global_lock:
            with self._lock:
                s: str = self._shm.get(self._sum)
                return int(s) if s is not None else 0

    @property
    def state(self) -> WindowState:
        """Get the current state of the storage."""
        # fmt: off
        lua_script = """
        local key_list = KEYS[1]
        local key_sum = KEYS[2]
        -- Retrieve the list of values
        local data = redis.call("LRANGE", key_list, 0, -1)
        -- Retrieve the stored sum (if the key does not exist, default to 0)
        local stored_sum = tonumber(redis.call("GET", key_sum) or "0")
        -- Calculate the sum of the list elements
        local calculated_sum = 0
        for i, v in ipairs(data) do
            calculated_sum = calculated_sum + tonumber(v)
        end
        -- If the sums do not match, return an error
        if calculated_sum ~= stored_sum then
            return {err="Sum mismatch: calculated sum (" .. calculated_sum .. ") does not equal stored sum (" .. stored_sum .. ")"}
        end
        return {data, stored_sum}
        """  # noqa: E501
        # fmt: on
        with self._redis_global_lock:
            with self._lock:
                data, sum_ = self._shm.eval(lua_script, 2, self._data, self._sum)
                return WindowState(data=data, sum=sum_)

    def slide(self, n: int) -> None:
        """Shift the window to the right by n frames.

        This operation removes the last n elements (discarding their values)
        and prepends n zeros at the beginning, automatically recalculating
        and updating the window's sum.

        :param n: The number of frames to slide.
        """
        lua_script = """
        local key_list = KEYS[1]
        local key_sum = KEYS[2]
        local n = tonumber(ARGV[1])
        local removed_sum = 0
        for i = 1, n do
            local val = redis.call("RPOP", key_list)
            if val then
                removed_sum = removed_sum + tonumber(val)
            end
            redis.call("LPUSH", key_list, "0")
        end
        local current_sum = tonumber(redis.call("GET", key_sum) or "0")
        local new_sum = current_sum - removed_sum
        redis.call("SET", key_sum, new_sum)
        """
        with self._redis_global_lock:
            with self._lock:
                self._shm.eval(lua_script, 2, self._data, self._sum, str(n))

    def as_list(self) -> list[int]:
        """Get the current sliding window as a list of integers.

        :return: List of window values.
        """
        with self._redis_global_lock:
            with self._lock:
                lst = self._shm.lrange(self._data, 0, -1)
                return [int(x) for x in lst]

    def clear(self) -> None:
        """Clear the sliding window by resetting all elements to zero."""
        with self._redis_global_lock:
            with self._lock:
                self._shm.delete(self._data)
                self._shm.rpush(self._data, *([0] * self.capacity))
                self._shm.set(self._sum, 0)

    def close(self) -> None:
        """Close the Redis connection and associated resources."""
        with self._redis_global_lock:
            with self._lock:
                _mute(self._shm.close())

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
        lua_script = """
        local key_list = KEYS[1]
        local key_sum = KEYS[2]
        local inc_value = tonumber(ARGV[1])
        local frame_limit = tonumber(ARGV[2])
        local window_limit = tonumber(ARGV[3])
        local current_value = tonumber(redis.call("LINDEX", key_list, 0) or "0")
        local new_value = current_value + inc_value
        local current_sum = tonumber(redis.call("GET", key_sum) or "0")
        local new_sum = current_sum + inc_value
        if frame_limit > 0 and new_value > frame_limit then
          return {err="frame limit exceeded"}
        end
        if new_value < 0 then
          return {err="frame overflow"}
        end
        if window_limit > 0 and new_sum > window_limit then
          return {err="window limit exceeded"}
        end
        if new_sum < 0 then
          return {err="window overflow"}
        end
        redis.call("LSET", key_list, 0, new_value)
        redis.call("SET", key_sum, new_sum)
        return new_value
        """
        try:
            self._shm.eval(lua_script, 2, self._data, self._sum, str(value), str(frame_limit), str(window_limit))
        except ResponseError as e:
            error_message = str(e)
            if "frame limit exceeded" in error_message:
                raise FrameLimitError("Frame limit exceeded") from e
            elif "window limit exceeded" in error_message:
                raise WindowLimitError("Window limit exceeded") from e
            elif "window overflow" in error_message:
                raise WindowOverflowError("Window sum value must be >= 0.") from e
            elif "frame overflow" in error_message:
                raise FrameOverflowError("Frame value must be >= 0.") from e
            else:
                raise e

    def __getitem__(self, index: int) -> int:
        """Get the element at the specified index from the sliding window.

        :param index: The index of the element.
        :return: The integer value at the specified index.
        """
        with self._redis_global_lock:
            with self._rlock:
                val: str = self._shm.lindex(self._data, index)
                return int(val) if val is not None else 0

    def __setitem__(self, index: int, value: int) -> None:
        lua_script = """
        local key_list = KEYS[1]
        local key_sum = KEYS[2]
        local new_value = tonumber(ARGV[1])
        local current_sum = tonumber(redis.call("GET", key_sum) or "0")
        local old_value = tonumber(redis.call("LINDEX", key_list, 0) or "0")
        local new_sum = current_sum - old_value + new_value
        redis.call("LSET", key_list, 0, new_value)
        redis.call("SET", key_sum, new_sum)
        """
        with self._redis_global_lock:
            with self._lock:
                self._shm.eval(lua_script, 2, self._data, self._sum, str(value))
