
CallGate - Awesome Rate Limiter
=================================


.. |made-with-python| image:: https://img.shields.io/badge/Made%20with-Python-1f425f.svg
   :target: https://www.python.org/

.. image:: https://img.shields.io/static/v1?label=ruff&message=passed&color=success
   :alt: Ruff
   :target: https://github.com/SerGeRybakov/call_gate/actions?query=workflow%3A%22Lint%22

.. image:: https://img.shields.io/static/v1?label=mypy&message=passed&color=success
   :alt: Mypy
   :target: https://github.com/SerGeRybakov/call_gate/actions?query=workflow%3A%22Type+Check%22

.. image:: https://img.shields.io/static/v1?label=pytest&message=passed&color=brightgreen
   :alt: Pytest
   :target: https://github.com/SerGeRybakov/call_gate/actions?query=workflow%3A%22Test%22

.. |CI| image::https://github.com/SerGeRybakov/call_gate/actions/workflows/workflow.yml/badge.svg
   :target: https://github.com/SerGeRybakov/call_gate/actions/workflows/workflow.yml

.. image:: https://img.shields.io/github/workflow/status/SerGeRybakov/call_gate/CI
   :alt: CI Status
   :target: https://github.com/SerGeRybakov/call_gate/actions

.. image:: https://codecov.io/gh/SerGeRybakov/call_gate/graph/badge.svg?token=NM5VXTXF21
   :target: https://codecov.io/gh/SerGeRybakov/call_gate

.. |PyPI version fury.io| image:: https://badge.fury.io/py/ansicolortags.svg
   :target: https://pypi.python.org/pypi/ansicolortags/

.. |PyPI license| image:: https://img.shields.io/pypi/l/ansicolortags.svg
   :target: https://pypi.python.org/pypi/ansicolortags/

.. |PyPI pyversions| image:: https://img.shields.io/pypi/pyversions/ansicolortags.svg
   :target: https://pypi.python.org/pypi/ansicolortags/

.. |GitHub make-a-pull-requests| image:: https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square
   :target: http://makeapullrequest.com

.. |Open Source Love svg1| image:: https://badges.frapsoft.com/os/v1/open-source.svg?v=103
   :target: https://github.com/ellerbrock/open-source-badges/

.. |Awesome Badges| image:: https://img.shields.io/badge/badges-awesome-green.svg
   :target: https://github.com/Naereen/badges


Overview
--------

This project implements a sliding window time-bound rate limiter, which allows tracking events over a configurabletime window divided into equal frames. Each frame tracks increments and decrements within a specific time period
defined by the frame step.

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

You can install CallGate using pip:

.. code-block:: bash

    pip install call_gate

You may also optionally install redis along with ``call_gate``:

.. code-block:: bash

    pip install call_gate[redis]

Or you may install them separately:

.. code-block:: bash

    pip install call_gate
    pip install redis  # >=5.0.0

Usage
-----

Creating
~~~~~~~~

Use the ``CallGate`` class to create a new **named** rate limiter with gate size and a frame step:

.. code-block:: python

    from datetime import timedelta
    from call_gate import CallGate

    gate = CallGate("my_gate", 10, 1)
    # what is equivalent to
    # gate = CallGate("my_gate", timedelta(seconds=10), timedelta(seconds=1))

This creates a gate with a size of 10 seconds and a frame step of 1 second.
Name is mandatory and important: it is used to identify the gate when using shared storage, especially Redis.

Using ``timedelta`` allows to set these parameters more precisely and flexible:

.. code-block:: python

   gate = CallGate(
       name="my_gate",
       gate_size=timedelta(seconds=1),
       frame_step=timedelta(milliseconds=1),
   )

While timedelta allows you to set even microseconds, you shall a realist and remember that Python is not that fast.
Some operations may definitely take some microseconds but usually your code needs some milliseconds or longer
to switch context, perform a loop, etc. You shall also take into consideration network latency if you use remote Redis
or make calls to other remote services.

Setting Limits
~~~~~~~~~~~~~~

Basically, the gate has two limits:

- ``gate_limit``: how many values can be in the whole gate
- ``frame_limit``: granular limit for each frame in the gate.

Both of them a set to zero by default. You can set any of them as follows:

For example:

.. code-block:: python

   gate = CallGate(
       name="my_gate",
       gate_size=timedelta(seconds=1),
       frame_step=timedelta(milliseconds=1),
       gate_limit=600,
       frame_limit=2
   )

What does it mean? This gate has a total scope of 1 second divided by 1 millisecond, what makes this gate rather large:
1000 frames. And the defined limits tell us that in each millisecond we can perform no more than 2 actions.
If the limit is exceeded, we will have to wait until we find ourselves in the next millisecond.
But the gate limit will reduce us to 600 total actions during 1 second.
You can easily calculate, that during 1 second we shall consume the major limit in the first 300 milliseconds
and the rest of the time our code be waiting until the total ``gate.sum`` is reduced.
It will be reduced frame-by-frame. Each time, when the sliding window slides by one frame, a sum is recalculated.
Thus, we will do 600 calls more or less quickly and after it we'll start doing slowly and peacefully, frame-by-frame:
2 calls per 1 millisecond.

The best pattern is to follow the rate-limit documentation of the service which you are using.

For example, in 2025 Gmail API has the following rate-limits for mail **sending** via 1 account (mailbox):
- 2 emails per second but no more than 1200 emails within last 10 minutes;
- 2000 emails per day.

This leads us to the following:

.. code-block:: python

    gate10m = CallGate(name="gmail10m",
       gate_size=timedelta(minutes=10),
       frame_step=timedelta(seconds=1),
       gate_limit=1200,
       frame_limit=2
    )

    gate24h = CallGate(name="gmail24h",
       gate_size=timedelta(days=1),
       frame_step=timedelta(minutes=1),
       gate_limit=2000,
    )

Both of these windows shall be used simultaneously in a sending script on each API call.

Storage Options
~~~~~~~~~~~~~~~

The library provides three storage options:

- ``simple``: (default) simple storage with a ``collections.deque``;
- ``shared``: shared memory storage using multiprocessing SyncManager ``list`` and ``Value`` for sum;
- ``redis``: Redis storage (requires ``redis`` package and a running Redis-server).

You can specify the storage option when creating the gate either as a string or as one of the ``GateStorageType`` keys:

.. code-block:: python

    gate = CallGate("gate_name", timedelta(seconds=10), timedelta(seconds=1), storage="shared")

The ``simple`` (default) storage is a thread-safe and pretend to be a process-safe as well. But you shall not rely
on it for using in multiple processes.

The ``shared`` storage is a thread-safe and process-safe. You can use it safely
in multiple processes. The main disadvantage of these storages - they are in-memory and do not save their state between
restarts.

The solution is ``redis`` storage, which is also thread-safe and process-safe as well and distributable. You
can easily use the same gate in multiple processes, even in separated Docker-containers connected to the same
Redis-server.

The coroutine-safety is provided for all of them by the main class: ``CallGate``.

Updating
~~~~~~~~

Actually, the only method you will need is the ``update`` method:

.. code-block:: python

    # try to increment the current frame value by 1,
    # wait if any limit is exceeded
    # commit an increment when the "gate is open"
    gate.update()

    await gate.update(
              5,          # try to increment the current frame value by 5
              throw=True  # throw an error if any limit is exceeded
          )

Updating as a Decorator
~~~~~~~~~~~~~~~~~~~~~~~

You can also use the gate as a decorator for functions and coroutines:

.. code-block:: python

    @gate(5, throw=True)
    def my_function():
        # code here

    @gate()
    async def my_coroutine():
        # code here

Updating as a Context Manager
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can also use the gate as a context manager with functions and coroutines:

.. code-block:: python

    def my_function(gate):
        with gate(5, throw=True):
            # code here


    async def my_coroutine(gate):
        async with gate():
            # code here

Asynchronous Usage
~~~~~~~~~~~~~~~~~~

As you could have already understood, ``CallGate`` can also be used asynchronously.

There are 3 public methods that can be used vice-versa:

.. code-block:: python

    import asyncio

    async def main(gate):
        await gate.update()        # increment the current frame value by 1
        await gate.check_limits()  # check if any limit is reached, raise error if true
        await gate.clear()         # clear the gate (set all frames and sum to zero)

    if __name__ == "__main__":
        gate = CallGate("my_async_gate", timedelta(seconds=10), timedelta(seconds=1))
        asyncio.run(main(gate))

Error Handling
--------------

The library raises specific exceptions for common errors, such as ``FrameLimitError`` and ``GateLimitError``.

You can catch these exceptions to handle errors:

.. code-block:: python

    while True:
        try:
            gate.update(5, throw=True)
        except FrameLimitError:
            print("Frame limit exceeded!")

Examples
~~~~~~~~~~~~
.. code-block:: python

    import asyncio
    from datetime import datetime, timedelta

    from call_gate import CallGate


    def dummy_func(gate: CallGate):
        requests = 0

        while requests < 30:
            with gate(throw=False):
                requests += 1
                print(f"\r{gate.data = }, {gate.sum = }, {requests = }", end="", flush=True)

        data, sum_ = gate.state

        print(end="\n")
        print(f"\rData: {data}, gate sum: {sum_}, Requests made:, {requests}, {datetime.now()},", flush=True)


    async def async_dummy(gate: CallGate):
        requests = 0

        while requests < 30:
            await gate.update()
            requests += 1
            print(f"\r{gate.data = }, {gate.sum = }, {requests = }", end="", flush=True)

        data, sum_ = gate.state

        print(end="\n")
        print(f"\rData: {data}, gate sum: {sum_}, Requests made:, {requests}, {datetime.now()},", flush=True)


    if __name__ == "__main__":
        gate = CallGate(
            "my_gate",
            timedelta(seconds=3),
            frame_step=timedelta(milliseconds=300),
            gate_limit=10,
            frame_limit=2,
        )
        print("Starting sync", datetime.now())
        dummy_func(gate)

        print("Starting async", datetime.now())
        asyncio.run(async_dummy(gate))

        for _ in range(10):
            gate.update()
            print(gate.current_frame, gate.state)

Testing
-------

The library includes a test suite to ensure its functionality. You can run the tests using pytest:

.. code-block:: bash

    pytest tests/

License
-------

This project is licensed under the MIT License. See the LICENSE file for details.

Contributing
------------

Contributions are welcome! If you have any ideas or bug reports, please open an issue or submit a pull request.
