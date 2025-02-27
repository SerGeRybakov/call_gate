# Sliding Window Time-Bound Counter

## Overview

This project implements a sliding window time-bound counter, which allows tracking events over a configurable time 
window divided into equal frames. Each frame tracks increments and decrements within a specific time period defined 
by the `frame_step`. 

The window maintains only the values within the window bounds, automatically removing outdated frames as new 
periods start.

## Features

- Automatically manages frame data based on the current time and window configuration
- Supports limits on both frame and window values, raising `FrameLimitError` or `GateLimitError` if exceeded
- Provides various data storage options, including in-memory, shared memory, and Redis
- Includes error handling for common scenarios, with specific exceptions derived from base errors within the library
- Supports asynchronous and synchronous usage

## Usage

### Creating a Sliding Window

To create a sliding window, you can use the `CallGate` class:

```python
from datetime import timedelta
from call_gate import CallGate

window = CallGate("my_window", timedelta(seconds=10), timedelta(seconds=1))
```

This creates a sliding window with a window size of 10 seconds and a frame step of 1 second.

### Updating the Window

To update the window, you can use the `update` method:

```python
window.update()  # increment the current frame value by 1
window.update(5)  # increment the current frame value by 5
```

### Using the Window as a Decorator

You can also use the window as a decorator for functions and coroutines:

```python
@window(5, throw=False)
def my_function():
    # code here
```

This will increment the current frame value by 5 before executing the function.

### Example Use Case

Here's an example use case:

```python
import time

window = CallGate(timedelta(seconds=10), timedelta(seconds=1))

while True:
    window.update(1)  # increment the current frame value by 1
    print(window.get_current_frame_value())  # print the current frame value
    time.sleep(1)
```

This will create a sliding window and increment the current frame value by 1 every second, printing the current frame value.

### Asynchronous Usage

You can also use the window asynchronously:

```python
import asyncio

async def main():
    window = CallGate(timedelta(seconds=10), timedelta(seconds=1))
    await window.update(5)  # increment the current frame value by 5
    print(await window.get_current_frame_value())  # print the current frame value

asyncio.run(main())
```

## Storage Options

The library provides three storage options:

- In-memory storage using a `collections.deque`
- Shared memory storage using a `multiprocessing.SharedMemory` buffer
- Redis storage using the `redis` package

You can specify the storage option when creating the window:

```python
window = CallGate(timedelta(seconds=10), timedelta(seconds=1), storage="shared")
```

## Error Handling

The library raises specific exceptions for common errors, such as `FrameLimitError` and `GateLimitError`. You can catch these exceptions to handle errors:

```python
try:
    window.update(5)
except FrameLimitError:
    print("Frame limit exceeded!")
```

## Testing

The library includes a test suite to ensure its functionality. You can run the tests using pytest:

```bash
pytest tests/
```

## License

This project is licensed under the MIT License. See the LICENSE file for details.

## Contributing

Contributions are welcome! If you have any ideas or bug reports, please open an issue or submit a pull request.

## Authors

Your Name

## Acknowledgments

[List any acknowledgments or credits here]

## API Documentation

### CallGate Class

- `__init__(window_size, frame_step, storage="in-memory")`: Initializes a new sliding window with the given window size, frame step, and storage option.
- `update(value)`: Updates the current frame value by the given value.
- `get_current_frame_value()`: Returns the current frame value.
- `get_window_size()`: Returns the window size.
- `get_frame_step()`: Returns the frame step.

### Exceptions

- `FrameLimitError`: Raised when the frame limit is exceeded.
- `GateLimitError`: Raised when the window limit is exceeded.

### Example Code

See the examples directory for example code demonstrating the usage of the library.
