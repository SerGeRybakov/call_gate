import random
import time

from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import dateutil
import pytest

from sliding_window import SlidingWindow
from sliding_window.errors import FrameLimitError, WindowLimitError


class TestSlidingWindowInit:
    def test_empty_init_fails(self):
        with pytest.raises(TypeError):
            assert SlidingWindow()

    @pytest.mark.parametrize(
        ("window_size", "frame_step"),
        [
            (1, 0.5),
            (4.0, 1),
            (timedelta(minutes=1), timedelta(seconds=5)),
            (timedelta(minutes=1), 0.5),
            (60 * 4.0, timedelta(seconds=5)),
            (timedelta(minutes=1), 1),
            (60 * 4, timedelta(seconds=5)),
            (timedelta(milliseconds=2), timedelta(microseconds=1000)),
            (4.0, 0.4),
            (timedelta(milliseconds=1), timedelta(microseconds=1)),
            (timedelta(milliseconds=1), timedelta(microseconds=10)),
            (timedelta(milliseconds=1), timedelta(microseconds=100)),
        ],
    )
    def test_init_success(self, window_size, frame_step):
        window = SlidingWindow(window_size, frame_step)
        assert window
        if not isinstance(window_size, timedelta):
            window_size = timedelta(seconds=window_size)
        if not isinstance(frame_step, timedelta):
            frame_step = timedelta(seconds=frame_step)
        assert window.window_size == window_size
        assert window.frame_step == frame_step
        assert window.frames == int(window_size // frame_step)
        assert window.window_limit == 0
        assert window.frame_limit == 0
        assert not window.data
        assert not window.current_dt
        assert window.timezone == ZoneInfo("UTC")
        assert window.sum == 0
        win_dict = {
            "window_size": window_size.total_seconds(),
            "frame_step": frame_step.total_seconds(),
            "timezone": "UTC",
            "window_limit": 0,
            "frame_limit": 0,
            "data": [],
            "current_dt": None,
            "sum": 0,
        }
        assert window.as_dict() == win_dict
        d = win_dict.copy()
        d.pop("data")
        d.pop("current_dt")
        d.pop("sum")
        win_repr = f"SlidingWindow({', '.join(f'{k}={v}' for k, v in d.items())})"
        assert win_repr == repr(window)
        assert win_repr == str(window)
        assert window.current_frame.value == 0
        assert window.last_frame.value == 0

    @pytest.mark.parametrize(
        ("window_size", "frame_step"),
        [
            (1, 1),
            (timedelta(minutes=1), timedelta(seconds=61)),
            (timedelta(microseconds=1), timedelta(milliseconds=1)),
            (timedelta(seconds=1), timedelta(milliseconds=6)),
            (timedelta(milliseconds=11), timedelta(microseconds=7)),
        ],
    )
    def test_init_fails_window_size_and_or_granularity(self, window_size, frame_step):
        with pytest.raises(ValueError):
            assert SlidingWindow(window_size, frame_step)

    @pytest.mark.parametrize(
        ("window_limit", "frame_limit"),
        [
            (2.0, 1),
            (2, 1.0),
            (2.0, 1.0),
            ("2", "1"),
            (True, 0),
            (0, True),
            (False, 1),
            (1, False),
            (None, 1),
            (1, None),
            ([], 1),
            (1, []),
            ((), 1),
            (1, ()),
            (set(), 1),
            (1, set()),
            ({}, 1),
            (1, {}),
        ],
    )
    def test_init_fails_limits_wrong_type(self, window_limit, frame_limit):
        with pytest.raises(TypeError):
            assert SlidingWindow(10, 5, window_limit=window_limit, frame_limit=frame_limit)

    @pytest.mark.parametrize(
        "params",
        [
            dict(window_limit=-1),
            dict(frame_limit=-2),
            dict(window_limit=-10, frame_limit=-5),
        ],
    )
    def test_init_fails_limits_wrong_value(self, params):
        with pytest.raises(ValueError):
            assert SlidingWindow(10, 5, **params)

    def test_init_fails_frame_limit_exceeds_window_limit(self):
        with pytest.raises(ValueError):
            assert SlidingWindow(10, 5, window_limit=1, frame_limit=2)

    @pytest.mark.parametrize(
        ("window_limit", "frame_limit"),
        [(0, 0), (1, 0), (2, 0), (0, 1), (0, 2), (2, 1)],
    )
    def test_init_window_limit_frame_limit(self, window_limit, frame_limit):
        window = SlidingWindow(10, 5, window_limit=window_limit, frame_limit=frame_limit)
        assert window.window_limit == window_limit
        assert window.frame_limit == frame_limit

    @pytest.mark.parametrize(
        "data",
        [
            (),
            [],
            [1],
            (0,),
            [0, 1],
            [1, 2],
            (0, 1),
            (1, 2),
        ],
    )
    def test_init_data(self, data):
        window = SlidingWindow(10, 5, data=data)
        win_data = []
        win_data.extend(data)
        assert window.data == win_data

    @pytest.mark.parametrize(
        "data",
        [
            ("1",),
            [
                "1",
            ],
            [[1]],
            1,
            {1, 2},
            {0: 1},
            [1, None],
            [1, True],
            [1, False],
        ],
    )
    def test_init_data_fail_on_type(self, data):
        with pytest.raises(TypeError):
            assert SlidingWindow(10, 5, data=data)

    @pytest.mark.parametrize(
        "data",
        [
            (1, 2, 3),
            [1, 2, 3],
        ],
    )
    def test_init_data_fail_on_value(self, data):
        with pytest.raises(ValueError):
            assert SlidingWindow(10, 5, data=data)

    @pytest.mark.parametrize(
        "current_dt",
        [
            None,
            "2024-01-01T00:00:00Z",
            "2024-01-01T00:00:00+01:00",
            "2024-01-01T00:00:00-05:30",
            "2024-01-01T00:00:00.000001+01:00",
            "2024-01-01T00:00:00.123456+01:00",
            "2024-01-01T00:00:00.123+01:00",
            "2024-01-01 00:00:00Z",
            "2024-01-01-00:00:00Z",
        ],
    )
    def test_init_timestamps(self, current_dt):
        window = SlidingWindow(10, 5, current_dt=current_dt)
        assert window.current_dt == (dateutil.parser.parse(current_dt) if current_dt is not None else current_dt)

    @pytest.mark.parametrize(
        "current_dt",
        [
            False,
            True,
            (),
            [],
            ["2024-01-01"],
            ("2024-01-01",),
            ["2024-01-01T00:00:00Z", "2024-01-01T00:00:01Z"],
            ("2024-01-01T00:00:00Z", "2024-01-01T00:00:01Z"),
            ("2024-01-01T00:00:00+01:00", "2024-01-01T00:00:01Z"),
            (1,),
            [[1]],
            1,
            0,
            {1, 2},
            {0: 1},
            {"2024-01-01T00:00:00Z", "2024-01-01T00:00:01Z"},
            ["2024-01-01T00:00:00Z", None],
            ["2024-01-01T00:00:00Z", True],
            ["2024-01-01T00:00:00Z", False],
            ("1",),
            ("1",),
            ["2024"],
            ["2024-1-1T00:00:00Z"],
            ["2024-01-01T00:00:00Z", "2024-01-01T00:00:01Z", "2024-01-01T00:00:02Z"],
            ("2024-01-01T00:00:00Z", "2024-01-01T00:00:01Z", "2024-01-01T00:00:02Z"),
        ],
    )
    def test_init_timestamps_fail_on_type(self, current_dt):
        with pytest.raises(TypeError):
            SlidingWindow(10, 5, current_dt=current_dt)

    @pytest.mark.parametrize(
        "current_dt",
        [
            "01",
            "2024-01",
            "2024",
            "2024-1-1",
            "2024-13-12T00:00:01Z",
            "2024-11-31T00:00:01Z",
            "2024-01-01  00:00:00Z",
            "",
            "   ",
            "20240101000000Z",
            "20240101 000000Z",
            "20240101-000000Z",
        ],
    )
    def test_init_timestamps_fail_on_value(self, current_dt):
        with pytest.raises(ValueError):
            assert SlidingWindow(10, 5, current_dt=current_dt)

    @pytest.mark.parametrize("sum", [0, 1, 2, 2**128, -1, -2, -(2**128)])
    def test_init_sum(self, sum):
        window = SlidingWindow(10, 5, sum=sum)
        assert window.sum == sum

    @pytest.mark.parametrize(
        "sum",
        [
            "0",
            1.0,
            None,
            True,
            False,
            [],
            (),
            {},
            set(),
            [2],
            (2**128,),
            {-1},
            {-2: 1},
        ],
    )
    def test_init_sum_fail_on_type(self, sum):
        with pytest.raises(TypeError):
            assert SlidingWindow(10, 5, sum=sum)

    def test_init_from_dict(self):
        old_window = SlidingWindow(10, 5)
        for _ in range(100):
            old_window.update(random.randint(3, 5))
            old_window.dec(random.randint(1, 3))
        new_window = SlidingWindow(**old_window.as_dict())
        assert new_window.window_size == old_window.window_size
        assert new_window.frame_step == old_window.frame_step
        assert new_window.window_limit == old_window.window_limit
        assert new_window.frame_limit == old_window.frame_limit
        assert new_window.frames == old_window.frames
        assert new_window.current_dt == old_window.current_dt
        assert new_window.data == old_window.data
        assert new_window.sum == old_window.sum
        assert new_window.timezone == old_window.timezone


class TestSlidingWindowIncAndDec:
    def test_increment(self, sliding_window_2s_1s_no_limits):
        assert sliding_window_2s_1s_no_limits.sum == 0
        sliding_window_2s_1s_no_limits.update()
        assert sliding_window_2s_1s_no_limits.sum == 1

    @pytest.mark.parametrize("value", [1, 2, 2**128])
    def test_increment_value(self, sliding_window_2s_1s_no_limits, value):
        assert sliding_window_2s_1s_no_limits.sum == 0
        sliding_window_2s_1s_no_limits.update(value)
        assert sliding_window_2s_1s_no_limits.sum == value

    @pytest.mark.parametrize(
        "value",
        [
            "0",
            1.0,
            None,
            True,
            False,
            [],
            (),
            {},
            set(),
            [2],
            (2**128,),
            {-1},
            {-2: 1},
        ],
    )
    def test_increment_value_fails_on_type(self, sliding_window_2s_1s_no_limits, value):
        with pytest.raises(TypeError):
            assert sliding_window_2s_1s_no_limits.update(value)

    @pytest.mark.parametrize("value", [0, -1, -2, -(2**128)])
    def test_increment_value_fails_on_zero_and_negative_values(self, sliding_window_2s_1s_no_limits, value):
        with pytest.raises(ValueError):
            assert sliding_window_2s_1s_no_limits.update(value)

    def test_decrement_raises_on_single_empty_frame(self, sliding_window_2s_1s_no_limits):
        assert sliding_window_2s_1s_no_limits.sum == 0
        assert len(sliding_window_2s_1s_no_limits) == 0
        with pytest.raises(ValueError):
            sliding_window_2s_1s_no_limits.dec()

    def test_decrement_raises_on_larger_value(self, sliding_window_2s_1s_no_limits):
        assert sliding_window_2s_1s_no_limits.sum == 0
        assert len(sliding_window_2s_1s_no_limits) == 0
        sliding_window_2s_1s_no_limits.update()
        with pytest.raises(ValueError):
            sliding_window_2s_1s_no_limits.dec(random.randint(2, 2**128))

    def test_decrement_one(self, sliding_window_2s_1s_no_limits):
        assert sliding_window_2s_1s_no_limits.sum == 0
        assert len(sliding_window_2s_1s_no_limits) == 0
        sliding_window_2s_1s_no_limits.update()
        sliding_window_2s_1s_no_limits.dec()
        assert sliding_window_2s_1s_no_limits.sum == 0
        assert len(sliding_window_2s_1s_no_limits) == 1

    @pytest.mark.xfail(reason="Window may have moved to another one frame while refreshing")
    def test_decrement_many_onetime(self):
        window = SlidingWindow(timedelta(seconds=1), timedelta(milliseconds=1))
        assert window.sum == 0
        assert len(window) == 0
        while not datetime.now(tz=window.timezone).microsecond < 100000:
            continue
        increments = 1000
        for i in range(increments):
            window.update()
        cur_val = window.current_frame.value
        assert cur_val < increments
        dec_value = 999
        window.dec(dec_value)
        assert window.sum == 1
        assert window.current_frame.value == 0
        assert window.last_frame.value == 1
        assert all([window.data[i] <= 1 for i in range(1, len(window) - 1)])

    def test_decrement_many_onetime_but_a_bit_less(self):
        window = SlidingWindow(timedelta(seconds=1), timedelta(milliseconds=1))
        assert window.sum == 0
        assert len(window) == 0
        while not datetime.now(tz=window.timezone).microsecond < 1000:
            continue
        increments = 1000
        for i in range(increments):
            window.update()
        time.sleep(0.5)
        cur_val = window.current_frame.value
        assert cur_val < increments
        assert window.sum == 1000
        dec_value = 300
        window.dec(dec_value)
        assert window.sum == 700
        assert window.current_frame.value == 0

    def test_decrement_many_onetime_raises_on_strict(self):
        window = SlidingWindow(timedelta(seconds=1), timedelta(milliseconds=500))
        assert window.sum == 0
        assert len(window) == 0
        while not datetime.now(tz=window.timezone).microsecond < 100000:
            continue
        increments = 351000
        for i in range(increments):
            window.update()
        time.sleep(0.5)
        with pytest.raises(ValueError):
            window.dec(window.sum - 1, strict=True)

    def test_decrement_many_onetime_raises_after_sleep(self):
        window = SlidingWindow(timedelta(seconds=1), timedelta(milliseconds=100))
        assert window.sum == 0
        assert len(window) == 0
        while not datetime.now(tz=window.timezone).microsecond < 300000:
            continue
        for i in range(1000):
            window.update()
            time.sleep(0.001)
        dec_value = 998
        time.sleep(0.5)
        window.update()
        assert window.sum < dec_value
        with pytest.raises(ValueError):
            assert window.dec(dec_value)

    @pytest.mark.parametrize(
        "value",
        [
            "0",
            1.0,
            None,
            True,
            False,
            [],
            (),
            {},
            set(),
            [2],
            (2**128,),
            {-1},
            {-2: 1},
        ],
    )
    def test_decrement_value_fails_on_type(self, sliding_window_2s_1s_no_limits, value):
        with pytest.raises(TypeError):
            assert sliding_window_2s_1s_no_limits.dec(value)

    @pytest.mark.parametrize("value", [-1, -2, -(2**128)])
    def test_decrement_value_fails_on_negative_values(self, sliding_window_2s_1s_no_limits, value):
        with pytest.raises(ValueError):
            assert sliding_window_2s_1s_no_limits.dec(value)

    def test_increment_until_full(self, sliding_window_2s_1s_no_limits):
        start = datetime.now()
        while datetime.now() < start + timedelta(seconds=2):
            sliding_window_2s_1s_no_limits.update()
        assert len(sliding_window_2s_1s_no_limits.data) == sliding_window_2s_1s_no_limits.frames

    def test_increment_replaces_old_data(self, sliding_window_2s_1s_no_limits):
        work = 1.6
        start = datetime.now()
        while datetime.now() < start + timedelta(seconds=work):
            sliding_window_2s_1s_no_limits.update()
        first_cur_frame_time = sliding_window_2s_1s_no_limits.current_frame.dt
        assert int(first_cur_frame_time.timestamp()) == int(datetime.now().timestamp())
        assert len(sliding_window_2s_1s_no_limits.data) == sliding_window_2s_1s_no_limits.frames
        win_sum = sliding_window_2s_1s_no_limits.sum
        last_data = sliding_window_2s_1s_no_limits.last_frame.value
        odata = sliding_window_2s_1s_no_limits.data.copy()
        time.sleep(1)
        sliding_window_2s_1s_no_limits.update()
        ndata = sliding_window_2s_1s_no_limits.data.copy()
        assert first_cur_frame_time == sliding_window_2s_1s_no_limits.last_frame.dt
        assert (
            round(sliding_window_2s_1s_no_limits.current_frame.dt.timestamp())
            == round(first_cur_frame_time.timestamp()) + 1
        )
        assert sliding_window_2s_1s_no_limits.sum == (win_sum - last_data + 1)

    def test_increment_replaces_old_data_after_long_sleep(self, sliding_window_2s_1s_no_limits):
        start = datetime.now()
        while datetime.now() < start + timedelta(seconds=2):
            sliding_window_2s_1s_no_limits.update()
        odata = deepcopy(sliding_window_2s_1s_no_limits.data)
        win_sum = sliding_window_2s_1s_no_limits.sum

        time.sleep(2)

        sliding_window_2s_1s_no_limits.update()
        ndata = deepcopy(sliding_window_2s_1s_no_limits.data)

        assert sliding_window_2s_1s_no_limits.sum < win_sum
        assert sliding_window_2s_1s_no_limits.sum == 1
        for idx in range(len(sliding_window_2s_1s_no_limits)):
            assert odata[idx] != ndata[idx]

    def test_increment_replaces_old_data_after_short_sleep(self):
        sliding_window = SlidingWindow(timedelta(seconds=4), timedelta(seconds=1))
        start = datetime.now()
        while datetime.now() < start + timedelta(seconds=4):
            sliding_window.update()
        dt = sliding_window.current_dt
        win_sum = sliding_window.sum
        odata = list(sliding_window.data.copy())
        sleep = 2
        time.sleep(sleep)
        sliding_window.update()
        ndata = list(sliding_window.data)
        assert dt == sliding_window.current_dt - sliding_window.frame_step * sleep
        assert sliding_window.data[sleep - 1] == 0
        assert odata[:sleep] == ndata[sleep:]
        assert sliding_window.sum < win_sum

    def test_clean(self, sliding_window_2s_1s_no_limits):
        assert len(sliding_window_2s_1s_no_limits) == 0
        assert sliding_window_2s_1s_no_limits.sum == 0
        assert sliding_window_2s_1s_no_limits.data == []
        assert sliding_window_2s_1s_no_limits.current_dt is None
        sliding_window_2s_1s_no_limits.update()
        assert len(sliding_window_2s_1s_no_limits) == 1
        assert sliding_window_2s_1s_no_limits.sum == 1
        assert sliding_window_2s_1s_no_limits.data == [1]
        assert isinstance(sliding_window_2s_1s_no_limits.current_dt, datetime)
        sliding_window_2s_1s_no_limits.clean()
        assert len(sliding_window_2s_1s_no_limits) == 1
        assert sliding_window_2s_1s_no_limits.sum == 0
        assert sliding_window_2s_1s_no_limits.data == [0]
        assert sliding_window_2s_1s_no_limits.current_dt is None


class TestSlidingWindowLimits:
    def test_window_limit(self, sliding_window_window_2s_1s_wl5):
        start = datetime.now()
        with pytest.raises(WindowLimitError):
            while datetime.now() < start + timedelta(
                seconds=sliding_window_window_2s_1s_wl5.window_size.total_seconds()
            ):
                sliding_window_window_2s_1s_wl5.update()

    def test_frame_limit(self, sliding_window_frame_2s_1s_fl5):
        start = datetime.now()
        with pytest.raises(FrameLimitError):
            while datetime.now() < start + timedelta(
                seconds=sliding_window_frame_2s_1s_fl5.window_size.total_seconds()
            ):
                sliding_window_frame_2s_1s_fl5.update()

    def test_both_limits(self):
        sliding_window = SlidingWindow(timedelta(seconds=4), timedelta(seconds=1), window_limit=10, frame_limit=2)
        sliding_window.update(5)
        with pytest.raises(FrameLimitError):
            sliding_window.update()
        time.sleep(1.1)
        sliding_window.update(5)
        assert sliding_window.sum == 10
        time.sleep(1.1)
        with pytest.raises(WindowLimitError):
            sliding_window.update()


if __name__ == "__main__":
    pytest.main()
