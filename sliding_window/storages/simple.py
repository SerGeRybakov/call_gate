import warnings
from collections import deque
from threading import Lock, RLock
from typing import Optional

from sliding_window.base.base_storage import BaseWindowStorage
from sliding_window.errors import SlidingWindowValueError, FrameLimitError, WindowLimitError


class SimpleWindowStorage(BaseWindowStorage):

    def __get_clear_deque(self):
        return deque([0] * self.capacity, maxlen=self.capacity)

    def __init__(self, name: str, capacity: int, *, data: Optional[list[int]] = None) -> None:
        super().__init__(name, capacity)
        self._lock: Lock = Lock()
        self._rlock: RLock = RLock()
        with self._lock:
            self._data: deque = self.__get_clear_deque()
            if data:
                self._data.extendleft(data)

    @property
    def sum(self) -> int:
        with self._rlock:
            return sum(self.as_list())

    def close(self):
        self._data.clear()

    def slide(self, n: int) -> None:
        with self._lock:
            if n < 1:
                raise SlidingWindowValueError("Value must be >= 1.")
            self._data.extendleft([0] * n)

    def as_list(self) -> list:
        with self._rlock:
            return list(self._data)

    def clear(self) -> None:
        with self._lock:
            self._data = self.__get_clear_deque()

    def atomic_update(self, value: int, frame_limit: int, window_limit: int):
        """
        Атомарно увеличивает значение текущего кадра и обновляет сумму окна.
        Если новый кадр или суммарное значение превышают лимиты, выбрасывается OverflowError.
        """
        with self._lock:
            current_value = self._data[0]
            new_value = current_value + value
            current_sum = sum(self._data)
            new_sum = current_sum + value

            if frame_limit > 0 and new_value > frame_limit:
                raise FrameLimitError("Frame limit exceeded")
            if window_limit > 0 and new_sum > window_limit:
                raise WindowLimitError("Window limit exceeded")
            if new_sum < 0 or new_value < 0:
                raise SlidingWindowOverflowError("Value must be >= 0.")

            self._data[0] = new_value
            return new_value

    def __getitem__(self, index: int) -> int:
        with self._rlock:
            return int(self._data[index])

    def __setitem__(self, index: int, value: int) -> None:
        with self._lock:
            self._data[index] = value
