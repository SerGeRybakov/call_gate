"""
Redis-based storage.

This module contains a storage implementation using Redis as the storage engine.

The storage is suitable for distributed applications. The storage uses a Redis list to store
the gate values. The Redis list is divided into frames which are accessed by the index of
the frame.

The storage is thread-safe and process-safe for multiple readers and writers.

The storage supports persistence of the gate values. When the application is restarted,
the gate values are not lost.
"""

import time
import uuid

from threading import get_ident
from types import TracebackType
from typing import Any, Optional

from redis import Redis, ResponseError
from typing_extensions import Unpack

from call_gate import FrameLimitError, GateLimitError
from call_gate.errors import CallGateValueError, FrameOverflowError, GateOverflowError
from call_gate.storages.base_storage import BaseStorage
from call_gate.typings import State


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
            if current_owner == self.owner:
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


class RedisStorage(BaseStorage):
    """Redis-based storage.

    This module contains a storage implementation using Redis as the storage engine.

    The storage is suitable for distributed applications. The storage uses a Redis list to store
    the gate values. The Redis list is divided into frames which are accessed by the index of
    the frame.

    The storage is thread-safe and process-safe for multiple readers and writers.

    The storage supports persistence of the gate values. When the application is restarted,
    the gate values are not lost.

    :param name: The name of the gate.
    :param capacity: The maximum number of values that the storage can store.
    :param data: Optional initial data for the storage.
    """

    def __init__(
        self, name: str, capacity: int, *, data: Optional[list[int]] = None, **kwargs: Unpack[dict[str, Any]]
    ) -> None:
        """Initialize the RedisStorage."""
        self.name = name
        self.capacity = capacity
        # Save the connection parameters for subsequent restoration
        self._redis_kwargs = kwargs.copy()
        self._redis_kwargs.pop("manager", None)
        self._redis_kwargs.pop("decode_responses", None)
        self._redis_kwargs["decode_responses"] = True
        if "db" not in self._redis_kwargs:
            self._redis_kwargs["db"] = 15

        self._client: Redis = Redis(**self._redis_kwargs)
        self._data: str = self.name  # Redis key для списка
        self._sum: str = f"{self.name}:sum"  # Redis key для суммы
        self._lock = self._client.lock(f"{self.name}:lock", blocking=True, timeout=1, blocking_timeout=1)
        self._rlock = RedisReentrantLock(self._client, self.name)

        # Lua script for initialization: sets the list and computes the sum.
        lua_script = """
        local key_list = KEYS[1]
        local key_sum = KEYS[2]
        local capacity = tonumber(ARGV[1])
        local providedCount = #ARGV - 1  -- data is passed starting from the second argument

        -- Function to adjust the list to the desired size
        local function adjust_list(list, cap)
          local len = #list
          if len < cap then
            for i = len + 1, cap do
              table.insert(list, "0")
            end
          elseif len > cap then
            -- Remove excess elements from the end
            while #list > cap do
              table.remove(list, cap + 1)
            end
          end
          return list
        end

        -- Check if the key exists
        local exists = redis.call("EXISTS", key_list)

        if exists == 1 then
          -- Key exists
          local currentList = redis.call("LRANGE", key_list, 0, -1)
          if providedCount > 0 then
            -- Data provided: prepend them
            local newList = {}
            -- First, insert the provided data (maintaining order: ARGV[2] becomes first)
            for i = 2, #ARGV do
              table.insert(newList, ARGV[i])
            end
            -- Then, add existing elements
            for i = 1, #currentList do
              table.insert(newList, currentList[i])
            end
            -- Adjust the final list to the size of capacity
            newList = adjust_list(newList, capacity)
            -- Overwrite the list in Redis
            redis.call("DEL", key_list)
            for i = 1, capacity do
              redis.call("RPUSH", key_list, newList[i])
            end
            currentList = newList
          else
            -- No data provided: adjust existing list to the size of capacity (if necessary)
            currentList = adjust_list(currentList, capacity)
            redis.call("DEL", key_list)
            for i = 1, capacity do
              redis.call("RPUSH", key_list, currentList[i])
            end
          end

          -- Calculate the sum of the final list
          local total = 0
          for i = 1, capacity do
            total = total + tonumber(currentList[i])
          end
          redis.call("SET", key_sum, total)
          return total

        else
          -- Key does not exist
          local newList = {}
          if providedCount > 0 then
            -- Data provided: fill the list with data
            for i = 2, #ARGV do
              table.insert(newList, ARGV[i])
            end
          end
          -- If no data is provided or there is too little/much - adjust the list to the size of capacity
          newList = adjust_list(newList, capacity)
          -- Create the list in Redis
          for i = 1, capacity do
            redis.call("RPUSH", key_list, newList[i])
          end
          -- Calculate the sum
          local total = 0
          for i = 1, capacity do
            total = total + tonumber(newList[i])
          end
          redis.call("SET", key_sum, total)
          return total
        end
        """
        with self._rlock:
            with self._lock:
                if data is not None:
                    args = [str(self.capacity)] + [str(x) for x in data]
                else:
                    args = [str(self.capacity)]
                self._client.eval(lua_script, 2, self._data, self._sum, *args)

    def __del__(self) -> None:
        try:
            self._client.close()
        except Exception:  # noqa: S110
            pass

    def clear(self) -> None:
        """Clear the sliding storage by resetting all elements to zero."""
        lua_script = """
        local key_list = KEYS[1]
        local key_sum = KEYS[2]
        local capacity = tonumber(ARGV[1])
        local data = {}
        local total = 0

        for i = 1, capacity do
            table.insert(data, "0")
        end
        redis.call("DEL", key_list)
        for i = 1, #data do
            redis.call("RPUSH", key_list, data[i])
        end
        redis.call("SET", key_sum, total)
        """
        with self._rlock:
            with self._lock:
                self._client.eval(lua_script, 2, self._data, self._sum, str(self.capacity))

    @property
    def sum(self) -> int:
        """Property to get the current sum of the storage from Redis.

        :return: The sum of the storage.
        """
        with self._rlock:
            with self._lock:
                s: str = self._client.get(self._sum)
                return int(s) if s is not None else 0

    @property
    def state(self) -> State:
        """Get the current state of the storage."""
        # fmt: off
        lua_script = """
        local key_list = KEYS[1]
        local key_sum = KEYS[2]
        -- Retrieve the list of values
        local data = redis.call("LRANGE", key_list, 0, -1)
        -- Retrieve the stored sum (if the key does not exist, default to 0)
        local stored_sum = tonumber(redis.call("GET", key_sum) or "0")
        -- Calculate the sum of the list elements and convert them to numbers
        local calculated_sum = 0
        local numeric_data = {}
        for i, v in ipairs(data) do
            local num = tonumber(v)
            numeric_data[i] = num
            calculated_sum = calculated_sum + num
        end
        -- If the sums do not match, return an error
        if calculated_sum ~= stored_sum then
            return {err="Sum mismatch: calculated sum (" .. calculated_sum .. ") does not equal stored sum (" .. stored_sum .. ")"}
        end
        return {numeric_data, stored_sum}
        """  # noqa: E501
        # fmt: on
        with self._rlock:
            with self._lock:
                data, sum_ = self._client.eval(lua_script, 2, self._data, self._sum)
                return State(data=data, sum=sum_)

    def slide(self, n: int) -> None:
        """Slide the storage to the right by n frames.

        This operation removes the last n elements (discarding their values)
        and prepends n zeros at the beginning, automatically recalculating
        and updating the storage's sum.

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
        if n < 1:
            raise CallGateValueError("Value must be >= 1.")
        if n >= self.capacity:
            self.clear()
        with self._rlock:
            with self._lock:
                self._client.eval(lua_script, 2, self._data, self._sum, str(n))

    def as_list(self) -> list[int]:
        """Get the current sliding storage as a list of integers.

        :return: List of storage values.
        """
        with self._rlock:
            with self._lock:
                lst = self._client.lrange(self._data, 0, -1)
                return [int(x) for x in lst]

    def atomic_update(self, value: int, frame_limit: int, gate_limit: int) -> None:
        """Atomically update the value of the most recent frame and the storage sum.

        If the new value of the most recent frame or the storage sum exceeds the corresponding limit,
        the method raises a FrameLimitError or GateLimitError exception.

        If the new value of the most recent frame or the storage sum is less than 0,
        the method raises a CallGateOverflowError exception.

        :param value: The value to add to the most recent frame value.
        :param frame_limit: The maximum allowed value of the most recent frame.
        :param gate_limit: The maximum allowed value of the storage sum.
        :raises FrameLimitError: If the new value of the most recent frame exceeds the frame limit.
        :raises GateLimitError: If the new value of the storage sum exceeds the gate limit.
        :raises CallGateOverflowError: If the new value of the most recent frame or the storage sum is less than 0.
        :return: The new value of the most recent frame.
        """
        lua_script = """
        local key_list = KEYS[1]
        local key_sum = KEYS[2]
        local inc_value = tonumber(ARGV[1])
        local frame_limit = tonumber(ARGV[2])
        local gate_limit = tonumber(ARGV[3])
        local current_value = tonumber(redis.call("LINDEX", key_list, 0) or "0")
        local new_value = current_value + inc_value
        local current_sum = tonumber(redis.call("GET", key_sum) or "0")
        local new_sum = current_sum + inc_value
        if frame_limit > 0 and new_value > frame_limit then
          return {err="Frame limit exceeded"}
        end
        if gate_limit > 0 and new_sum > gate_limit then
          return {err="Gate limit exceeded"}
        end
        if new_sum < 0 then
          return {err="Gate overflow"}
        end
        if new_value < 0 then
          return {err="Frame overflow"}
        end
        redis.call("LSET", key_list, 0, new_value)
        redis.call("SET", key_sum, new_sum)
        return new_value
        """
        try:
            self._client.eval(lua_script, 2, self._data, self._sum, str(value), str(frame_limit), str(gate_limit))
        except ResponseError as e:
            error_message = str(e)
            if "Frame limit exceeded" in error_message:
                raise FrameLimitError("Frame limit exceeded") from e
            if "Gate limit exceeded" in error_message:
                raise GateLimitError("Gate limit exceeded") from e
            if "Gate overflow" in error_message:
                raise GateOverflowError("Gate sum value must be >= 0.") from e
            if "Frame overflow" in error_message:
                raise FrameOverflowError("Frame value must be >= 0.") from e
            raise e

    def __getitem__(self, index: int) -> int:
        """Get the element at the specified index from the storage.

        :param index: The index of the element.
        :return: The integer value at the specified index.
        """
        with self._rlock:
            with self._rlock:
                val: str = self._client.lindex(self._data, index)
                return int(val) if val is not None else 0

    def __getstate__(self) -> dict:
        """Get the serializable state of the object.

        Excludes non-serializable objects (Redis client and locks).
        """
        state = self.__dict__.copy()
        # Remove non-serializable objects
        state.pop("_client", None)
        state.pop("_lock", None)
        state.pop("_rlock", None)
        return state

    def __reduce__(self) -> tuple[type["RedisStorage"], tuple[str, int], dict[str, Any]]:
        """Support the pickle protocol.

        Returns a tuple with the constructor call and the state of the object.
        """
        return self.__class__, (self.name, self.capacity), self.__getstate__()

    def __setstate__(self, state: dict) -> None:
        """Restore the state of the object from a serialized dictionary.

        Restores the Redis connection and recreates the locks.
        """
        self.__dict__.update(state)

        self._client = Redis(**self._redis_kwargs)
        self._lock = self._client.lock(f"{self.name}:lock", blocking=True, timeout=1, blocking_timeout=1)
        self._rlock = RedisReentrantLock(self._client, self.name)
