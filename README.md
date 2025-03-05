<div align="center">

# CallGate - Awesome Rate Limiter

[![Ruff](https://img.shields.io/static/v1?label=ruff&message=passed&color=success)](https://github.com/SerGeRybakov/call_gate/actions?query=workflow%3A%22Lint%22)
[![Mypy](https://img.shields.io/static/v1?label=mypy&message=passed&color=success)](https://github.com/SerGeRybakov/call_gate/actions?query=workflow%3A%22Type+Check%22)
[![Pytest](https://img.shields.io/static/v1?label=pytest&message=passed&color=brightgreen)](https://github.com/SerGeRybakov/call_gate/actions?query=workflow%3A%22Test%22)
[![Codecov](https://codecov.io/gh/SerGeRybakov/call_gate/graph/badge.svg?token=NM5VXTXF21)](https://codecov.io/gh/SerGeRybakov/call_gate)
[![CI Status](https://img.shields.io/github/workflow/status/SerGeRybakov/call_gate/CI?style=flat-square)](https://github.com/SerGeRybakov/call_gate/actions)
[![CI](https://github.com/SerGeRybakov/call_gate/actions/workflows/workflow.yml/badge.svg)](https://github.com/SerGeRybakov/call_gate/actions/workflows/workflow.yml)

[![PyPI version](https://badge.fury.io/py/ansicolortags.svg)](https://pypi.python.org/pypi/ansicolortags/)
[![License](https://img.shields.io/pypi/l/ansicolortags.svg)](https://pypi.python.org/pypi/ansicolortags/)
[![Python Versions](https://img.shields.io/badge/Python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://www.python.org/)

[![Open Source Love](https://badges.frapsoft.com/os/v1/open-source.svg?v=103)](https://github.com/ellerbrock/open-source-badges/) 
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](http://makeapullrequest.com)

</div>

## Overview

This project implements a sliding window time-bound rate limiter, which allows tracking events over a configurable time window divided into equal frames. Each frame tracks increments and decrements within a specific time period defined by the frame step.

The CallGate maintains only the values within the set bounds, automatically removing outdated frames as new periods start.

## Features

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

## Installation

You can install CallGate using pip:

```bash
pip install call_gate
```

You may also optionally install redis along with `call_gate`:

```bash
pip install call_gate[redis]
```

Or you may install them separately:

```bash
pip install call_gate
pip install redis  # >=5.0.0
```

## How to?

### Create

Use the `CallGate` class to create a new **named** rate limiter with gate size and a frame step:

```python
from call_gate import CallGate

gate = CallGate("my_gate", 10, 1)
# what is equivalent to
# gate = CallGate("my_gate", timedelta(seconds=10), timedelta(seconds=1))
```
This creates a gate with a size of 10 seconds and a frame step of 1 second.
Name is mandatory and important: it is used to identify the gate when using shared storage, especially Redis.  

Using ``timedelta`` allows to set these parameters more precisely and flexible:

```python
from datetime import timedelta

from call_gate import CallGate

gate = CallGate(
    name="my_gate",
    gate_size=timedelta(seconds=1),
    frame_step=timedelta(milliseconds=1)
)
```

### Set Limits

Basically, the gate has two limits:

- ``gate_limit``: how many values can be in the whole gate
- ``frame_limit``: granular limit for each frame in the gate.

Both are set to zero by default. You can keep them zero (what is useless) or reset any of them
(or both of them) as follows:

```python
from datetime import timedelta

from call_gate import CallGate

gate = CallGate(
    name="my_gate",
    gate_size=timedelta(seconds=1),
    frame_step=timedelta(milliseconds=1),
    gate_limit=600,
    frame_limit=2
)
```
While timedelta allows you to set even microseconds, you shall be a realist and remember that Python is not that fast.
Some operations may definitely take some microseconds but usually your code needs some milliseconds or longer
to switch context, perform a loop, etc. You should also consider network latency if you use remote Redis
or make calls to other remote services.

### Choose Storage Options

The library provides three storage options:

- ``simple``: (default) simple storage with a ``collections.deque``;
- ``shared``: shared memory storage using multiprocessing SyncManager ``list`` and ``Value`` for sum;
- ``redis``: Redis storage (requires ``redis`` package and a running Redis-server).

You can specify the storage option when creating the gate either as a string or as one of the ``GateStorageType`` keys:

```python
from call_gate import GateStorageType

gate = CallGate(
    "my_gate", 
    timedelta(seconds=10), 
    timedelta(seconds=1), 
    storage=GateStorageType.shared  # <------ or "shared"
)
```

The ``simple`` (default) storage is a thread-safe and pretend to be a process-safe as well. But using it in multiple 
processes may be un-safe and may result in unexpected behaviour, so don't rely on it in multiprocessing 
or in WSGI/ASGI workers-forking applications.

The ``shared`` storage is a thread-safe and process-safe. You can use it safely in multiple processes 
and in WSGI/ASGI applications started from one parent process.

The main disadvantage of these two storages - they are in-memory and do not persist their state between restarts.

The solution is ``redis`` storage, which is not just thread-safe and process-safe as well, but also distributable.
You can easily use the same gate in multiple processes, even in separated Docker-containers connected 
to the same Redis-server.

Coroutine safety is ensured for all of them by the main class: ``CallGate``.

### Use directly

Actually, the only method you need is the ``update`` method:

```python
gate.update()
await gate.update(5, throw=True)
```

### Use as a Decorator

You can also use the gate as a decorator for functions and coroutines:


```python
@gate(5, throw=True)
def my_function():
    # code here

@gate()
async def my_coroutine():
    # code here
```

### Use as a Context Manager

You can also use the gate as a context manager with functions and coroutines:

```python
def my_function(gate):
    with gate(5, throw=True):
        # code here

async def my_coroutine(gate):
    async with gate():
        # code here
```

### Use Asynchronously

As you could have already understood, ``CallGate`` can also be used asynchronously.  

There are 3 public methods that can be used interchangeably:

```python
import asyncio

async def main(gate):
    await gate.update()
    await gate.check_limits()
    await gate.clear()

if __name__ == "__main__":
    gate = CallGate("my_async_gate", timedelta(seconds=10), timedelta(seconds=1))
    asyncio.run(main(gate))
```

### Handle Errors 

The package provides a pack of custom exceptions. Basically, you may be interested in the following: 

``FrameLimitError`` 
``GateLimitError``. 


```python
while True:
    try:
        gate.update(5, throw=True)
    except FrameLimitError:
        print("Frame limit exceeded!")
```

## Example

To understand how it works, run this code in your favourite IDE:

```python
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
    print(f"\rData: {data}, gate sum: {sum_}, Requests made:, {requests}, {datetime.now()},", flush=True)

async def async_dummy(gate: CallGate):
    requests = 0
    while requests < 30:
        await gate.update()
        requests += 1
        print(f"\r{gate.data = }, {gate.sum = }, {requests = }", end="", flush=True)
    data, sum_ = gate.state
    print(f"\rData: {data}, gate sum: {sum_}, Requests made:, {requests}, {datetime.now()},", flush=True)

if __name__ == "__main__":
    gate = CallGate("my_gate", timedelta(seconds=3), frame_step=timedelta(milliseconds=300), gate_limit=10, frame_limit=2)
    print("Starting sync", datetime.now())
    dummy_func(gate)
    print("Starting async", datetime.now())
    asyncio.run(async_dummy(gate))
```

## Testing
The code is covered with 1.5K test cases.

```bash
pytest tests/
```

## License

This project is licensed under the MIT License. See the LICENSE file for details.

## Contributing

Contributions are welcome! If you have any ideas or bug reports, please open an issue or submit a pull request.
