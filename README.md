<div align="center">

# CallGate - Awesome Rate Limiter

[![Ruff](https://img.shields.io/static/v1?label=ruff&message=passed&color=success)](https://github.com/SerGeRybakov/call_gate/actions?query=workflow%3A%22Lint%22)
[![Mypy](https://img.shields.io/static/v1?label=mypy&message=passed&color=success)](https://github.com/SerGeRybakov/call_gate/actions?query=workflow%3A%22Type+Check%22)
[![Pytest](https://img.shields.io/static/v1?label=pytest&message=passed&color=brightgreen)](https://github.com/SerGeRybakov/call_gate/actions?query=workflow%3A%22Test%22)
[![Codecov](https://codecov.io/gh/SerGeRybakov/call_gate/graph/badge.svg?token=NM5VXTXF21)](https://codecov.io/gh/SerGeRybakov/call_gate)
[![CI Status](https://img.shields.io/github/actions/workflow/status/SerGeRybakov/call_gate/workflow.yml?branch=main&style=flat-square&label=CI)](https://github.com/SerGeRybakov/call_gate/actions)
[![CI](https://github.com/SerGeRybakov/call_gate/actions/workflows/workflow.yml/badge.svg)](https://github.com/SerGeRybakov/call_gate/actions/workflows/workflow.yml)

[![PyPI version](https://img.shields.io/pypi/v/call_gate.svg)](https://pypi.org/project/call_gate/)
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
What does it mean? This gate has a total scope of 1 second divided by 1 millisecond, what makes this gate rather large:
1000 frames. And the defined limits tell us that within each millisecond we can perform no more than 2 actions.

f the limit is exceeded, we will have to wait until the next millisecond.
But the gate limit will reduce us to 600 total actions during 1 second.

You can easily calculate, that during 1 second we shall consume the major limit in the first 300 milliseconds
and the rest of the time our code will be waiting until the total ``gate.sum`` is reduced.

It will be reduced frame-by-frame. Each time, when the sliding window slides by one frame, a sum is recalculated.
Thus, we will do 600 calls more or less quickly and after it we'll start doing slowly and peacefully, frame-by-frame:
2 calls per 1 millisecond + waiting until the gate sum will be lower than 600.

The best practice is to follow the rate-limit documentation of the service which you are using.

For example, at the edge of 2024-2025 Gmail API has the following rate-limits for mail **sending**
via 1 account (mailbox):
- 2 emails per second, but no more than 1200 emails within last 10 minutes;
- 2000 emails within last 24 hours.

This leads us to the following:

```python
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
```
Both of these windows should be used simultaneously in a sending script on each API call.

While timedelta allows you to set even microseconds, you shall be a realist and remember that Python is not that fast.
Some operations may definitely take some microseconds but usually your code needs some milliseconds or longer
to switch context, perform a loop, etc. You should also consider network latency if you use remote Redis
or make calls to other remote services.

### Choose Storage

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
and in WSGI/ASGI applications started from one parent process. **Note**: For Hypercorn >= 0.18.0, you must 
disable daemon mode (`daemon = false` in config) to use shared memory storage with multiple workers.

The main disadvantage of these two storages - they are in-memory and do not persist their state between restarts.

The solution is ``redis`` storage, which is not just thread-safe and process-safe as well, but also distributable.
You can easily use the same gate in multiple processes, even in separated Docker-containers connected 
to the same Redis-server.

Coroutine safety is ensured for all of them by the main class: ``CallGate``.

### ASGI Server Compatibility

**Uvicorn & Gunicorn**: Work out of the box with all storage types.

**Hypercorn**: 
- **< 0.18.0**: Only `redis` storage works with multiple workers
- **>= 0.18.0**: All storage types work when daemon mode is disabled:
  ```bash
  # Using stdin config
  echo 'daemon = false' | hypercorn myapp:app --config /dev/stdin --workers 4
  
  # Using config file
  hypercorn myapp:app --config hypercorn.toml --workers 4
  ```

If you are using a remote Redis-server, just pass the 
[client parameters](https://redis-py.readthedocs.io/en/stable/connections.html) to the `CallGate` constructor `kwargs`:

```python
gate = CallGate(
    "my_gate", 
    timedelta(seconds=10), 
    timedelta(seconds=1), 
    storage=GateStorageType.redis,
    host="10.0.0.1",
    port=16379,
    db=0,
    password="secret",
    ...
) 
```
The default parameters are: 
- `host`: `"localhost"`
- `port`: `6379`, 
- `db`: `15`, 
- `password`: `None`.

Also, be noted that the client decodes the Redis-server responses by default. It can not be changed - the 
`decode_responses` parameter is ignored.

### Use Directly

Actually, the only method you need is the ``update`` method:

```python
# try to increment the current frame value by 1,
# wait while any limit is exceeded
# commit an increment when the "gate is open"
gate.update()

await gate.update(
          5,          # try to increment the current frame value by 5
          throw=True  # throw an error if any limit is exceeded
      )
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
- `ThrottlingError` - a base limit error, raised when rate limits are reached or violated.
- `FrameLimitError` - (derives from `ThrottlingError`) a limit error, raised when frame limit is reached or violated. 
- `GateLimitError` - (derives from `ThrottlingError`) a limit error, raised when gate limit is reached or violated.

These errors are handled automatically by the library, but you may also choose to throw them explicitly by switching
the `throw` parameter to `True`

```python
from call_gate import FrameLimitError, GateLimitError, ThrottlingError

while True:
    try:
        gate.update(5, throw=True)
    except FrameLimitError as e:
        print(f"Frame limit exceeded! {e}")
    except GateLimitError as e:
        print(f"Gate limit exceeded! {e}")
        
    # or
    
    # except ThrottlingError as e:
    #    print(f"Throttling Error! {e}")
```

The others may be found in [`call_gate.errors`](./call_gate/errors.py) module.

### Persist and Restore

If you need to persist the state of the gate between restarts, you can use the `gate.to_file({file_path})` method.  

To restore the state you can use the `restored = CallGate.from_file({file_path})` method.  

If you wish to restore the state using another storage type, you can pass the desired type as a keyword parameter to 
`restored = CallGate.from_metadata({file_path}, storage={storage_type})`method.

Redis persists the gate's state automatically until you restart its container without having shared volumes or clear 
the Redis database. But still you can save its state to the file and to restore it as well.

You may also use the `gate.as_dict()` method to get the state of the gate as a dictionary.

### Explore the Properties
The `CallGate` has a lot of useful properties:

```python
gate.name           # get the name of the gate
gate.gate_size      # get the gate size
gate.frame_step     # get the frame step
gate.gate_limit     # get the maximum limit of the gate
gate.frame_limit    # get the maximum limit of the frame
gate.storage        # get the storage type
gate.timezone       # get the gate timezone
gate.frames         # get the number of frames
gate.current_dt     # get the current frame datetime
gate.current_frame  # get the current frame datetime and value
gate.last_frame     # get the last frame datetime and value
gate.limits         # get the gate and frame limits
gate.sum            # get the sum of all values in the gate
gate.data           # get the values of the gate
gate.state          # get the sum and data of the gate atomically
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

## Remarkable Notes
- The package is compatible with Python 3.9+.
- Under `WSGI/ASGI applications` I mean the applications such as `gunicorn` or `uvicorn`. 
- **Hypercorn compatibility**: 
  - **Hypercorn < 0.18.0**: `CallGate` cannot be used with multiple workers as Hypercorn spawns each worker as a daemon process, which do not allow child processes.
  - **Hypercorn >= 0.18.0**: `CallGate` can be used by disabling daemon mode via configuration file:
    ```bash
    echo 'daemon = false' | hypercorn app:app --config /dev/stdin --workers 4
    ```
    Or using a TOML config file:
    ```toml
    # hypercorn.toml
    daemon = false
    ```
    ```bash
    hypercorn app:app --config hypercorn.toml --workers 4
    ```
  - There are special tests for both cases: ["test_hypercorn_server_daemon_behavior"](tests/test_asgi_wsgi.py) and ["test_hypercorn_no_daemon_rate_limit"](tests/test_asgi_wsgi.py).   
- All the updates are atomic, so no race conditions shall occur.
- The majority of Redis calls is performed via 
[Lua-scripts](https://redis.io/docs/latest/develop/interact/programmability/eval-intro/), what makes them run 
on the Redis-server side.
- The maximal value guaranteed for `in-memory` storages is `2**64 - 1`, but for Redis it is ``2**53 - 1``
only because Redis uses [Lua 5.1](https://www.lua.org/manual/5.1/).  
Lua 5.1 works with numbers as `double64` bit floating point numbers in 
[IEEE 754](https://en.wikipedia.org/wiki/IEEE_754) standard. Starting from ``2**53`` Lua loses precision.  
But for the purposes of this package even ``2**53 - 1`` is still big enough.
- If the timezone of your gate is important for any reason, it may be set using the `timezone` parameter 
in the `CallGate` constructor in the string format: "UTC", "Europe/London", "America/New_York", etc. By default,
it is `None`.
- If you need to control the gate's `data` and `sum` between the `update` calls, it's better to use `state` 
property instead of calling `sum` and `data`. Gate's `state` collects both values at once. And when you are calling 
`sum` and `data` one-by-one, the frame time may pass and the values may be out of sync.

## Testing
The code is covered with 1.5K test cases.

```bash
pytest tests/
```

## License

This project is licensed under the MIT License. See the LICENSE file for details.

## Contributing

Contributions are welcome! If you have any ideas or bug reports, please open an issue or submit a pull request.
