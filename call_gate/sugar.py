"""
CallGate Sugar.

This module contains utility functions for CallGate.
"""

import asyncio

from asyncio import iscoroutinefunction
from collections.abc import Awaitable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from functools import partial, wraps
from types import TracebackType
from typing import TYPE_CHECKING, Any, Callable, Optional, Union


if TYPE_CHECKING:
    from call_gate import CallGate


def dual(sync_method: Callable) -> Callable:
    """Make a method work both synchronously and asynchronously.

    If an event loop is already running, the method will execute in a thread pool,
    returning an awaitable object. Otherwise, the synchronous function is called directly.

    class A:

        @dual
        def method():
            ...

    a = A()
    a.method()
    await a.method()

    :param sync_method: synchronous method
    """

    @wraps(sync_method)
    def wrapper(
        self: "CallGate", *args: Any, **kwargs: Any
    ) -> Union[Coroutine[Any, Any, None], Callable[[Any, ...], Any]]:
        """Make a method work both synchronously and asynchronously.

        If an event loop is already running, the method will execute in a thread pool,
        returning an awaitable object. Otherwise, the synchronous function is called directly.

        :param self: The CallGate object to call the method on.
        :param args: Any arguments to pass to the method.
        :param kwargs: Any keyword arguments to pass to the method.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        async def async_inner(self: "CallGate", *args: Any, **kwargs: Any) -> None:
            """Run the method in a thread pool using the current event loop.

            :param self: The CallGate object to call the method on.
            :param args: Any arguments to pass to the method.
            :param kwargs: Any keyword arguments to pass to the method.
            """
            if self._alock is None:
                self._alock = asyncio.Lock()
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="CallGateAsync")
            if self._loop is None:
                self._loop = asyncio.get_running_loop()
            async with self._alock:
                future = partial(sync_method, self, *args, **kwargs)
                return await self._loop.run_in_executor(self._executor, future)

        if loop and loop.is_running():
            return async_inner(self, *args, **kwargs)
        else:
            return sync_method(self, *args, **kwargs)

    return wrapper


class _CallGateWrapper:
    """Internal class for wrapping a CallGate instance into a decorator.

    When a CallGate instance is used as a decorator, this class is used to wrap
    the CallGate instance and provide the decorator functionality.

    The class provides a __call__ method that is used as the decorator. The
    __call__ method takes a function or coroutine as an argument and returns
    a new function or coroutine that wraps the original one with the CallGate
    instance's update method.

    :param gate: CallGate instance.
    :param value: Value to be added to the counter.
    :param throw: Flag for throwing exceptions.
    """

    def __init__(self, gate: "CallGate", value: int, throw: bool):
        self.gate = gate
        self.value = value
        self.throw = throw

    # Method for use as a decorator
    def __call__(self, func: Callable) -> Union[Callable, Awaitable]:
        """Gate instance decorator for functions and coroutines.

        :param func: Function or coroutine to be wrapped.
        """

        @wraps(func)
        async def awrapper(*args: Any, **kwargs: Any) -> Any:
            """Async wrapper for functions and coroutines.

            This function is used as a decorator for functions and coroutines.
            It wraps the original function or coroutine with the CallGate
            instance's update method.

            :param args: Arguments to be passed to the wrapped function or coroutine.
            :param kwargs: Keyword arguments to be passed to the wrapped function or coroutine.
            :return: The result of the wrapped function or coroutine.
            """
            await self.gate.update(self.value, self.throw)
            return await func(*args, **kwargs)

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Sync wrapper for functions and coroutines.

            This function is used as a decorator for functions and coroutines.
            It wraps the original function or coroutine with the CallGate
            instance's update method.

            :param args: Arguments to be passed to the wrapped function or coroutine.
            :param kwargs: Keyword arguments to be passed to the wrapped function or coroutine.
            :return: The result of the wrapped function or coroutine.
            """
            self.gate.update(self.value, self.throw)
            return func(*args, **kwargs)

        if iscoroutinefunction(func):
            return awrapper
        return wrapper

    def __enter__(self) -> "CallGate":
        """Context manager entrance for CallGate.

        The context manager is used to automatically call the update method
        of the CallGate instance when entering the context and do nothing when
        exiting the context.

        :param self: CallGate instance.
        :return: The CallGate instance.
        """
        self.gate.update(self.value, self.throw)
        return self.gate

    def __exit__(
        self, exc_type: Optional[type[Exception]], exc_val: Optional[Exception], exc_tb: Optional[TracebackType]
    ) -> None:
        """Context manager exit for CallGate.

        The context manager is used to automatically call the update method
        of the CallGate instance when entering the context and do nothing when
        exiting the context.

        :param self: CallGate instance.
        :param exc_type: Type of exception raised.
        :param exc_val: Value of the exception raised.
        :param exc_tb: Traceback of the exception raised.
        """

    async def __aenter__(self) -> "CallGate":
        """Async context manager entrance for CallGate.

        The async context manager is used to automatically call the update method
        of the CallGate instance when entering the context and do nothing when
        exiting the context.

        :param self: CallGate instance.
        :return: The CallGate instance.
        """
        await self.gate.update(self.value, self.throw)
        return self.gate

    async def __aexit__(
        self, exc_type: Optional[type[Exception]], exc_val: Optional[Exception], exc_tb: Optional[TracebackType]
    ) -> None:
        """Async context manager exit for CallGate.

        The async context manager is used to automatically call the update method
        of the CallGate instance when entering the context and do nothing when
        exiting the context.

        :param self: CallGate instance.
        :param exc_type: Type of exception raised.
        :param exc_val: Value of the exception raised.
        """
        pass
