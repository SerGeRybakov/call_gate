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

import inspect
import pickle
import time
import uuid
import warnings

from datetime import datetime
from threading import get_ident
from types import TracebackType
from typing import Any, Optional, Union

from redis import Redis, RedisCluster, ResponseError
from redis.cluster import ClusterNode
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

    def __init__(self, client: Union[Redis, RedisCluster], name: str, timeout: int = 1) -> None:
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
    """Redis-based storage supporting both single Redis and Redis cluster.

    This storage implementation uses Redis as the storage engine and is suitable
    for distributed applications. The storage uses a Redis list to store the gate
    values divided into frames accessed by index.

    The storage is thread-safe and process-safe for multiple readers and writers.
    The storage supports persistence of gate values across application restarts.

    :param name: The name of the gate.
    :param capacity: The maximum number of values that the storage can store.
    :param data: Optional initial data for the storage.
    :param client: Pre-initialized Redis or RedisCluster client (recommended).
    :param kwargs: Redis connection parameters (deprecated, use client instead).
    """

    def _create_locks(self) -> None:
        """Create Redis locks for this storage instance."""
        self._lock = self._client.lock(f"{{{self.name}}}:lock", blocking=True, timeout=1, blocking_timeout=1)
        self._rlock = RedisReentrantLock(self._client, f"{{{self.name}}}")

    def __init__(
        self, name: str, capacity: int, *, data: Optional[list[int]] = None, **kwargs: Unpack[dict[str, Any]]
    ) -> None:
        """Initialize the RedisStorage."""
        self.name = name
        self.capacity = capacity

        # Check if pre-initialized client is provided
        client = kwargs.pop("client", None)

        if client is not None:
            # Use pre-initialized client
            self._client: Union[Redis, RedisCluster] = client

        else:
            # Use kwargs for backward compatibility
            redis_kwargs = {k: v for k, v in kwargs.items() if k not in {"manager"}}
            redis_kwargs["decode_responses"] = True
            if "db" not in redis_kwargs:
                redis_kwargs["db"] = 15

            # Add socket timeouts to prevent hanging on Redis operations
            if "socket_timeout" not in redis_kwargs:
                redis_kwargs["socket_timeout"] = 5.0
            if "socket_connect_timeout" not in redis_kwargs:
                redis_kwargs["socket_connect_timeout"] = 5.0

            self._client: Redis = Redis(**redis_kwargs)

        # Use hash tags to ensure all keys for this gate are in the same cluster slot
        self._data: str = f"{{{self.name}}}"  # Redis key for the list
        self._sum: str = f"{{{self.name}}}:sum"  # Redis key for the sum
        self._timestamp: str = f"{{{self.name}}}:timestamp"  # Redis key for the timestamp
        self._create_locks()

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

    def _is_serializable_and_add(self, key: str, value: Any, target_params: set, found_params: dict) -> bool:
        """Check if value is serializable and add to found_params if key matches target_params."""
        if key in target_params and key not in found_params:
            try:
                pickle.dumps(value)
                found_params[key] = value
                return True
            except (TypeError, pickle.PicklingError):
                pass
        return False

    def _can_recurse_into(self, value: Any) -> bool:
        """Check if we can recurse into this value (has __dict__ or is dict, but not primitive types)."""
        return (hasattr(value, "__dict__") or isinstance(value, dict)) and not isinstance(
            value, (str, int, float, bool, type(None))
        )

    def _merge_nested_params(self, nested_params: dict, found_params: dict) -> None:
        """Merge nested parameters into found_params, avoiding duplicates."""
        for k, v in nested_params.items():
            if k not in found_params:
                found_params[k] = v

    def _extract_and_merge_params(self, obj: Any, target_params: set, visited: set, found_params: dict) -> None:
        """Extract constructor parameters from object and merge them into found_params."""
        nested_params = self._extract_constructor_params(obj, target_params, visited)
        self._merge_nested_params(nested_params, found_params)

    def _process_connection_kwargs(self, obj: Any, target_params: set, found_params: dict) -> None:
        """Process special connection_kwargs attribute."""
        if not hasattr(obj, "connection_kwargs"):
            return

        kwargs = getattr(obj, "connection_kwargs", {})
        if hasattr(kwargs, "items"):  # Check if it's a dict
            for key, value in kwargs.items():
                self._is_serializable_and_add(key, value, target_params, found_params)

    def _extract_constructor_params(
        self, obj: Any, target_params: set, visited: Optional[set] = None
    ) -> dict[str, Any]:
        """Recursively extract constructor parameters from Redis client object."""
        if visited is None:
            visited = set()

        # Avoid circular references
        obj_id = id(obj)
        if obj_id in visited:
            return {}
        visited.add(obj_id)

        found_params: dict[str, Any] = {}

        try:
            self._process_object_dict(obj, target_params, visited, found_params)
            self._process_connection_kwargs(obj, target_params, found_params)
        except (AttributeError, TypeError):
            # Skip objects that don't support attribute access or have incompatible types
            pass

        return found_params

    def _process_object_dict(self, obj: Any, target_params: set, visited: set, found_params: dict) -> None:
        """Process object's __dict__ attributes."""
        if not hasattr(obj, "__dict__"):
            return

        obj_dict = getattr(obj, "__dict__", {})
        for key, value in obj_dict.items():
            self._process_attribute(key, value, target_params, visited, found_params)

    def _process_attribute(self, key: str, value: Any, target_params: set, visited: set, found_params: dict) -> None:
        """Process a single attribute from object's __dict__."""
        # Check for direct parameter matches first
        if self._is_serializable_and_add(key, value, target_params, found_params):
            return

        # Skip if not a target parameter or can't recurse
        if key in target_params or not self._can_recurse_into(value) or key.startswith("_"):
            return

        # Handle dictionaries and objects differently
        if isinstance(value, dict):
            self._process_dict_value(value, target_params, visited, found_params)
        else:
            self._extract_and_merge_params(value, target_params, visited, found_params)

    def _process_dict_value(self, value_dict: dict, target_params: set, visited: set, found_params: dict) -> None:
        """Process dictionary values for parameter extraction."""
        for dict_key, dict_value in value_dict.items():
            # Try to add as direct parameter match
            if self._is_serializable_and_add(dict_key, dict_value, target_params, found_params):
                continue
            # Recurse into nested objects within the dictionary
            if self._can_recurse_into(dict_value):
                self._extract_and_merge_params(dict_value, target_params, visited, found_params)

    def _extract_client_state(self) -> dict[str, Any]:
        """Extract client constructor parameters for serialization."""
        client_type = "cluster" if isinstance(self._client, RedisCluster) else "redis"

        # Get constructor signature from the client's class
        sig = inspect.signature(self._client.__class__.__init__)
        valid_params = set(sig.parameters.keys()) - {"self", "connection_pool"}

        # Extract constructor parameters recursively
        constructor_params = self._extract_constructor_params(self._client, valid_params)

        return {"client_type": client_type, "client_state": constructor_params}

    @staticmethod
    def _restore_client_from_state(client_type: str, client_state: dict[str, Any]) -> Union[Redis, RedisCluster]:
        """Restore Redis client from serialized state."""
        if client_type == "cluster":
            # Extract constructor parameters from state
            init_kwargs = {k: v for k, v in client_state.items() if k not in ["startup_nodes"] and v is not None}

            if startup_nodes_data := client_state.get("startup_nodes"):
                startup_nodes = [ClusterNode(node["host"], node["port"]) for node in startup_nodes_data]
                init_kwargs["startup_nodes"] = startup_nodes

            return RedisCluster(**init_kwargs)

        else:
            return Redis(**client_state)

    def clear(self) -> None:
        """Clear the sliding storage by resetting all elements to zero."""
        lua_script = """
        local key_list = KEYS[1]
        local key_sum = KEYS[2]
        local key_timestamp = KEYS[3]
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
        redis.call("DEL", key_timestamp)
        """
        with self._rlock:
            with self._lock:
                self._client.eval(lua_script, 3, self._data, self._sum, self._timestamp, str(self.capacity))

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
        local key_timestamp = KEYS[3]
        local n = tonumber(ARGV[1])
        local timestamp = ARGV[2]
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
        redis.call("SET", key_timestamp, timestamp)
        """
        if n < 1:
            raise CallGateValueError("Value must be >= 1.")
        if n >= self.capacity:
            self.clear()
        with self._rlock:
            with self._lock:
                current_timestamp = datetime.now().isoformat()
                self._client.eval(lua_script, 3, self._data, self._sum, self._timestamp, str(n), current_timestamp)

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
        local key_timestamp = KEYS[3]
        local inc_value = tonumber(ARGV[1])
        local frame_limit = tonumber(ARGV[2])
        local gate_limit = tonumber(ARGV[3])
        local timestamp = ARGV[4]
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
        redis.call("SET", key_timestamp, timestamp)
        return new_value
        """
        try:
            # Get current timestamp for atomic update
            current_timestamp = datetime.now().isoformat()
            self._client.eval(
                lua_script,
                3,
                self._data,
                self._sum,
                self._timestamp,
                str(value),
                str(frame_limit),
                str(gate_limit),
                current_timestamp,
            )
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

    def get_timestamp(self) -> Optional[datetime]:
        """Get the last update timestamp from storage.

        :return: The last update timestamp, or None if not set.
        """
        with self._rlock:
            with self._lock:
                ts_str: str = self._client.get(self._timestamp)
                if ts_str:
                    return datetime.fromisoformat(ts_str)
                return None

    def set_timestamp(self, dt: datetime) -> None:
        """Save the timestamp to storage.

        :param dt: The timestamp to save.
        """
        with self._rlock:
            with self._lock:
                self._client.set(self._timestamp, dt.isoformat())

    def clear_timestamp(self) -> None:
        """Clear the timestamp from storage."""
        with self._rlock:
            with self._lock:
                self._client.delete(self._timestamp)

    def __getitem__(self, index: int) -> int:
        """Get the element at the specified index from the storage.

        :param index: The index of the element.
        :return: The integer value at the specified index.
        """
        with self._rlock:
            with self._lock:
                val: str = self._client.lindex(self._data, index)
                return int(val) if val is not None else 0

    def __getstate__(self) -> dict[str, Any]:
        """Prepare for pickling."""
        state = self.__dict__.copy()
        # Remove non-serializable objects
        state.pop("_client", None)
        state.pop("_lock", None)
        state.pop("_rlock", None)

        # Extract client metadata (client must exist by this point)
        client_info = self._extract_client_state()
        state.update(client_info)  # Adds "client_type" and "client_state"

        return state

    def __reduce__(self) -> tuple[type["RedisStorage"], tuple[str, int], dict[str, Any]]:
        """Support the pickle protocol.

        Returns a tuple with the constructor call and the state of the object.
        """
        return self.__class__, (self.name, self.capacity), self.__getstate__()

    def __setstate__(self, state: dict[str, Any]) -> None:
        """Restore after unpickling."""
        # Extract client restoration data before updating __dict__
        client_type = state.pop("client_type")
        client_state = state.pop("client_state")

        # Update object state
        self.__dict__.update(state)

        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=DeprecationWarning, module="redis")
            self._client = self._restore_client_from_state(client_type, client_state)

        # Recreate locks using reusable method
        self._create_locks()
