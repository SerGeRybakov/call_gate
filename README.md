# Sliding window time-bound counter.

Sliding window is divided into equal frames basing on the window size and frame_step.
Each frame is bound to the frame_step set frame_step and keeps track of increments and decrements
within a time period equal to the frame frame_step. Values in the ``data[0]`` are always bound
to the current granular time frame_step. Tracking timestamp may be bound to a personalized timezone.

The window keeps only those values which are within the window bounds. The old values are removed
automatically when the window is full and the new frame period started.

The sum of the frames values increases while the window is not full. When it's full, the sum will
decrease on each slide, due to erasing of the outdated frames.

If the window was not used for a while and some (or all) frames are outdated and a new inc
is made, the outdated frames will be replaced with the new period from the current moment
up to the last valid timestamp (if there is one). In other words, on inc the window always
keeps frames from the current moment back to history, ordered by granular frame_step without any gaps.

If total and/or frame limit is set, the window will throw ThrottlingError if any of these limits
are exceeded. The error provides the information of the exceeded limit type and its value.

## Installation

```
pip install sliding-window -i https://${OWM_GIT_TOKEN}:${OWM_GIT_TOKEN_PASS}@pypi.owm.io/simple
```

## Integrate with your tools

Imagine, you have to call some external API with a limited number of requests per second. 
Let's say - 10 req/sec.

You need to create a window of a certain size, split in frames. Frame size shall be smaller than window size.
Let's say that 10 req/sec - is our frame limit. 

```python
import time
from datetime import datetime, timedelta
from sliding_window import SlidingTimeWindow
from sliding_window.errors import ThrottlingError

window = SlidingTimeWindow(
    window_size=timedelta(seconds=10),
    frame_step=timedelta(seconds=1),
    frame_limit=10,
)

requests = 0
print(f"Started at {datetime.now()}")
while requests < 100:
    try:
        window.check_limits()
    except ThrottlingError as e:
        print(datetime.now(), e, "Window sum:", window.sum, "Current frame:", window.current_frame)
        time.sleep(0.2)
        continue
    window.inc()
    requests += 1
    print(datetime.now(), "Requests made:", requests)
```

Or the external API has more strict limits: 10 req/sec but not more than 100 req/min.  
In this case our window size shall grow to 60 sec and frame size remains at 1 sec, and we set both limits.

```python
import time
from datetime import datetime, timedelta
from sliding_window import SlidingTimeWindow
from sliding_window.errors import ThrottlingError

window = SlidingTimeWindow(
    window_size=timedelta(seconds=60),
    window_limit=100,
    frame_step=timedelta(seconds=1),
    frame_limit=10,
)

requests = 0
print(f"Started at {datetime.now()}")
while requests < 150:
    try:
        window.check_limits()
    except ThrottlingError as e:
        print(datetime.now(), e, "Window sum:", window.sum, "Current frame:", window.current_frame)
        time.sleep(0.2)
        continue
    window.inc()
    requests += 1
    print(datetime.now(), "Requests made:", requests)
```

External APIs may have several limits. For example, Gmail API has:
- 2000 emails within last 24 hours:

```python
from datetime import timedelta

win24h = {
    "window_size": timedelta(hours=24), 
    "frame_step": timedelta(minutes=1), 
    "window_limit": 2000
}
```

- and 2 emails within 1 second but no more than 1200 emails within last 10 minutes: 
```python
from datetime import timedelta
win10m =  {
    "window_size": timedelta(minutes=10),
    "frame_step": timedelta(seconds=1),
    "window_limit": 1200,
    "frame_limit": 2,
}
```

## SlidingTimeWindow Public API
### Methods
- `inc()`: increment window and frame sums value by 1 or pass your **positive** number
- `dec()`: decrement window and frame sums by 1 or pass your **positive** number; `strict` flag indicates whether decrement below 0 is allowed or not
- `check_limits()`: check current window state; if any of the limits is reached one of the `WindowLimitError` or `FrameLimitError` (both are inherited from `ThrottlingError`) will be raised.
- `as_dict()`: serialize window to a dictionary; it may be useful if you want to persist its state across restarts
- `clean()`: wipe the window and its frames (set the sums to 0).

### Properties
- `current_dt`: get the datetime of the current frame
- `current_frame`: get current frame info
- `last_frame`: get last frame info
- `frame_limit`: get the maximum value limit for each frame in the window
- `frame_step`: get the step between each frame in the window as a timedelta
- `frames`: get total number of frames in the window
- `data`: get a list of current window frames with their values inside
- `sum`: get current window values sum
- `timezone`: get window timezone (UTC by default)
- `window_limit`: get window limit
- `window_size`: get the total window size as a timedelta
```
