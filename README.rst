CallGate - Awesome Rate Limiter
=================================

Overview
--------

This project implements a sliding window time-bound rate limiter, which allows tracking events over a configurable
time window divided into equal frames. Each frame tracks increments and decrements within a specific time period
defined by the ``frame_step``.

The CallGate maintains only the values within the set bounds, automatically removing outdated frames as new
periods start.

Features
--------
- Thread/Process/Coroutine safe
- Distributable
- Persistable and recoverable
- Easy to use
- Provides various data storage options, including in-memory, shared memory, and Redis
- Includes error handling for common scenarios, with specific exceptions derived from base errors within the library
- A lot of sugar (very sweet):
    - Supports asynchronous and synchronous calls
    - Works as asynchronous and synchronous context manager
    - Works as decorator for functions and coroutines


Installation
------------

You can install CallGate using pip::

    pip install call_gate

You may also optionally install redis along with ``call_gate``:

    pip install call_gate[redis]

Storage Options
---------------

The library provides three storage options:

- ``simple``: (default) simple storage with a ``collections.deque``;
- ``shared``: shared memory storage using multiprocessing SyncManager ``list`` and ``Value`` for sum;
- ``redis``: Redis storage (requires ``redis`` package and a running Redis-server).

You can specify the storage option when creating the gate either as a string or as one of the ``GateStorageType`` keys:

    gate = CallGate("gate_name", timedelta(seconds=10), timedelta(seconds=1), storage="shared")

The ``simple`` (default) storage is a thread-safe and pretend to be a process-safe as well. But you shall not rely
on it for using in multiple processes. The ``shared`` storage is a thread-safe and process-safe. You can use it safely
in multiple processes. The main disadvantage of these storages - they are in-memory and do not save their state between
restarts. The solution is ``redis`` storage, which is also thread-safe and process-safe as well and distributable. You
can easily use the same gate in multiple processes, even in separated Docker-containers connected to the same
Redis-server.

The coroutine-safety for all of them is provided by the main class: ``CallGate``.


Usage
-----

Creating
~~~~~~~~

Use the ``CallGate`` class to create a new **named** rate limiter:

    from datetime import timedelta
    from call_gate import CallGate

    gate = CallGate("my_gate", timedelta(seconds=10), timedelta(seconds=1))

This creates a gate with a size of 10 seconds and a frame step of 1 second.
The name is mandatory and important: it is used to identify the gate when using storages (especially Redis).


Updating
~~~~~~~~

To update the gate, you can use the ``update`` method:

    gate.update()  # increment the current frame value by 1, wait if any limit is exceeded

    await gate.update(5, throw=True)  # increment the current frame value by 5, throw an error if any limit is exceeded


Using as a Decorator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can also use the gate as a decorator for functions and coroutines:

    @gate(5, throw=True)  # increment the current frame value by 5, throw an error if any limit is exceeded
    def my_function():
        # code here

    @gate()  # increment the current frame value by 1, wait if any limit is exceeded
    async def my_coroutine():
        # code here

Using as a Context Manager
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can also use the gate as a context manager with functions and coroutines:

    def my_function(gate):
        with gate(5, throw=True):  # increment the current frame value by 5, throw an error if any limit is exceeded
            # code here


    async def my_coroutine(gate):
        async with gate():  # increment the current frame value by 1, wait if any limit is exceeded
            # code here

Example Use Case
~~~~~~~~~~~~~~~~

Here's an example use case:

    import time

    gate = CallGate("my_gate", timedelta(seconds=10), timedelta(seconds=1))

    while True:
        gate.update(1)  # increment the current frame value by 1
        print(gate.current_frame.value)  # print the current frame value
        time.sleep(1)

This will create a new gate and increment the current frame value by 1 every second, printing the current frame value.

Asynchronous Usage
~~~~~~~~~~~~~~~~~~

You can also use the gate asynchronously:

    import asyncio

    async def main(gate):
        await gate.update(5)  # increment the current frame value by 5
        print(await gate.get_current_frame_value())  # print the current frame value

    if __name__ == "__main__":
        gate = CallGate("my_async_gate", timedelta(seconds=10), timedelta(seconds=1))
        asyncio.run(main(gate))

Error Handling
--------------

The library raises specific exceptions for common errors, such as ``FrameLimitError`` and ``GateLimitError``.
You can catch these exceptions to handle errors:

    try:
        gate.update(5, throw=True)
    except FrameLimitError:
        print("Frame limit exceeded!")

Testing
-------

The library includes a test suite to ensure its functionality. You can run the tests using pytest:

    pytest tests/

License
-------

This project is licensed under the MIT License. See the LICENSE file for details.

Contributing
------------

Contributions are welcome! If you have any ideas or bug reports, please open an issue or submit a pull request.


Exceptions
~~~~~~~~~~

- ``FrameLimitError``: Raised when the frame limit is exceeded.
- ``GateLimitError``: Raised when the gate limit is exceeded.

Examples
~~~~~~~~~~~~

See the examples directory for example code demonstrating the usage of the library.
