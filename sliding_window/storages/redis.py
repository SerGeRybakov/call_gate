import uuid
import warnings
from threading import RLock, get_ident
from typing import List, Optional
from xmlrpc.client import ResponseError

from redis import Redis

from sliding_window import WindowLimitError, FrameLimitError
from sliding_window.base.base_storage import BaseWindowStorage
from sliding_window.typings import KWType


import time
import uuid
from threading import get_ident
from redis import Redis

class RedisReentrantLock:
    """Реализует переentrant (рекурсивный) распределённый лок на основе Redis.

    :param client: Экземпляр подключения к Redis.
    :param name: Уникальное имя лока.
    :param timeout: Время жизни лока в секундах.
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
            # Если лок уже захвачен текущим владельцем, просто инкрементируем счётчик и продлеваем TTL.
            if current_owner and current_owner.decode() == self.owner:
                self.client.hincrby(self.count_key, self.owner, 1)
                self.client.expire(self.lock_key, self.timeout)
                self.client.expire(self.owner_key, self.timeout)
                break
            # Пытаемся атомарно установить лок
            if self.client.set(self.lock_key, "1", nx=True, ex=self.timeout):
                # Лок успешно захвачен – устанавливаем владельца и начинаем счётчик с 1.
                self.client.set(self.owner_key, self.owner, ex=self.timeout)
                self.client.hset(self.count_key, self.owner, 1)
                break
            else:
                time.sleep(0.01)  # Небольшая задержка для избежания busy-wait
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        count = self.client.hincrby(self.count_key, self.owner, -1)
        if count <= 0:
            # Если счётчик дошёл до нуля – удаляем все связанные ключи
            self.client.delete(self.lock_key, self.owner_key, self.count_key)
        else:
            # Если ещё остаётся вложенных вызовов – продлеваем TTL
            self.client.expire(self.lock_key, self.timeout)
            self.client.expire(self.owner_key, self.timeout)



class RedisWindowStorage(BaseWindowStorage):
    """Redis-based storage for a sliding window implementation.

    This class uses Redis to store a fixed-size window of integers and
    maintains the sum of the window in a separate Redis key.
    """

    _data: str  # Redis key for our list
    _sum: str  # Redis key for the sum of the window

    def __init__(self, name: str, capacity: int, *, data: Optional[List[int]] = None, **kwargs: KWType) -> None:
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
        """
        Property to get the current sum of the window from Redis.

        :return: The sum of the window.
        """
        with self._redis_global_lock:
            with self._lock:
                s = self._shm.get(self._sum)
                return int(s) if s is not None else 0

    def slide(self, n: int) -> None:
        """
        Shift the window to the right by n frames.

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

    def as_list(self) -> List[int]:
        """
        Get the current sliding window as a list of integers.

        :return: List of window values.
        """
        with self._redis_global_lock:
            with self._lock:
                lst = self._shm.lrange(self._data, 0, -1)
                return [int(x) for x in lst]

    def clear(self) -> None:
        """
        Clear the sliding window by resetting all elements to zero.
        """
        with self._redis_global_lock:
            with self._lock:
                self._shm.delete(self._data)
                self._shm.rpush(self._data, *([0] * self.capacity))
                self._shm.set(self._sum, 0)

    def __getitem__(self, index: int) -> int:
        """
        Get the element at the specified index from the sliding window.

        :param index: The index of the element.
        :return: The integer value at the specified index.
        """
        with self._redis_global_lock:
            with self._rlock:
                val = self._shm.lindex(self._data, index)
                return int(val) if val is not None else 0

    def __setitem__(self, index: int, value: int) -> None:
        """
        Replace the value at the head (index 0) of the sliding window,
        automatically updating the window's sum.

        :param index: Ignored; the operation always affects the head (index 0).
        :param value: The new integer value to set at index 0.
        """
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

    def close(self) -> None:
        """
        Close the Redis connection and associated resources.
        """
        try:
            with self._redis_global_lock:
                with self._lock:
                    self._shm.close()
        except Exception as e:
            warnings.warn(f"Failed to close redis connection: {e}")


    def atomic_update(self, value: int, frame_limit: int, window_limit: int):
        """
        Атомарно увеличивает значение текущего кадра и общую сумму.
        Если новый кадр или сумма превышают соответствующие лимиты, возвращается ошибка.
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
        if window_limit > 0 and new_sum > window_limit then
          return {err="window limit exceeded"}
        end
        redis.call("LSET", key_list, 0, new_value)
        redis.call("SET", key_sum, new_sum)
        return new_value
        """
        try:
            result = self._shm.eval(lua_script, 2, self._data, self._sum, str(value), str(frame_limit),
                                    str(window_limit))
        except ResponseError as e:
            error_message = str(e)
            if "frame limit exceeded" in error_message:
                raise FrameLimitError("Frame limit exceeded") from e
            elif "window limit exceeded" in error_message:
                raise WindowLimitError("Window limit exceeded") from e
            else:
                raise e
        return result
