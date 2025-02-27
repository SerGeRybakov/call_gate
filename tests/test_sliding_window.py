import random
import time

from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import dateutil
import pytest

from call_gate import CallGate
from call_gate.errors import FrameLimitError, GateLimitError


class TestSlidinggateInit:
    def test_empty_init_fails(self):
        with pytest.raises(TypeError):
            assert CallGate()

    @pytest.mark.parametrize(
        ("gate_size", "frame_step"),
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
    def test_init_success(self, gate_size, frame_step):
        gate = CallGate(gate_size, frame_step)
        assert gate
        if not isinstance(gate_size, timedelta):
            gate_size = timedelta(seconds=gate_size)
        if not isinstance(frame_step, timedelta):
            frame_step = timedelta(seconds=frame_step)
        assert gate.gate_size == gate_size
        assert gate.frame_step == frame_step
        assert gate.frames == int(gate_size // frame_step)
        assert gate.gate_limit == 0
        assert gate.frame_limit == 0
        assert not gate.data
        assert not gate.current_dt
        assert gate.timezone == ZoneInfo("UTC")
        assert gate.sum == 0
        win_dict = {
            "gate_size": gate_size.total_seconds(),
            "frame_step": frame_step.total_seconds(),
            "timezone": "UTC",
            "gate_limit": 0,
            "frame_limit": 0,
            "data": [],
            "current_dt": None,
            "sum": 0,
        }
        assert gate.as_dict() == win_dict
        d = win_dict.copy()
        d.pop("data")
        d.pop("current_dt")
        d.pop("sum")
        win_repr = f"CallGate({', '.join(f'{k}={v}' for k, v in d.items())})"
        assert win_repr == repr(gate)
        assert win_repr == str(gate)
        assert gate.current_frame.value == 0
        assert gate.last_frame.value == 0

    @pytest.mark.parametrize(
        ("gate_size", "frame_step"),
        [
            (1, 1),
            (timedelta(minutes=1), timedelta(seconds=61)),
            (timedelta(microseconds=1), timedelta(milliseconds=1)),
            (timedelta(seconds=1), timedelta(milliseconds=6)),
            (timedelta(milliseconds=11), timedelta(microseconds=7)),
        ],
    )
    def test_init_fails_gate_size_and_or_granularity(self, gate_size, frame_step):
        with pytest.raises(ValueError):
            assert CallGate(gate_size, frame_step)

    @pytest.mark.parametrize(
        ("gate_limit", "frame_limit"),
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
    def test_init_fails_limits_wrong_type(self, gate_limit, frame_limit):
        with pytest.raises(TypeError):
            assert CallGate(10, 5, gate_limit=gate_limit, frame_limit=frame_limit)

    @pytest.mark.parametrize(
        "params",
        [
            dict(gate_limit=-1),
            dict(frame_limit=-2),
            dict(gate_limit=-10, frame_limit=-5),
        ],
    )
    def test_init_fails_limits_wrong_value(self, params):
        with pytest.raises(ValueError):
            assert CallGate(10, 5, **params)

    def test_init_fails_frame_limit_exceeds_gate_limit(self):
        with pytest.raises(ValueError):
            assert CallGate(10, 5, gate_limit=1, frame_limit=2)

    @pytest.mark.parametrize(
        ("gate_limit", "frame_limit"),
        [(0, 0), (1, 0), (2, 0), (0, 1), (0, 2), (2, 1)],
    )
    def test_init_gate_limit_frame_limit(self, gate_limit, frame_limit):
        gate = CallGate(10, 5, gate_limit=gate_limit, frame_limit=frame_limit)
        assert gate.gate_limit == gate_limit
        assert gate.frame_limit == frame_limit

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
        gate = CallGate(10, 5, data=data)
        win_data = []
        win_data.extend(data)
        assert gate.data == win_data

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
            assert CallGate(10, 5, data=data)

    @pytest.mark.parametrize(
        "data",
        [
            (1, 2, 3),
            [1, 2, 3],
        ],
    )
    def test_init_data_fail_on_value(self, data):
        with pytest.raises(ValueError):
            assert CallGate(10, 5, data=data)

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
        gate = CallGate(10, 5, current_dt=current_dt)
        assert gate.current_dt == (dateutil.parser.parse(current_dt) if current_dt is not None else current_dt)

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
            CallGate(10, 5, current_dt=current_dt)

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
            assert CallGate(10, 5, current_dt=current_dt)

    @pytest.mark.parametrize("sum", [0, 1, 2, 2**128, -1, -2, -(2**128)])
    def test_init_sum(self, sum):
        gate = CallGate(10, 5, sum=sum)
        assert gate.sum == sum

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
            assert CallGate(10, 5, sum=sum)

    def test_init_from_dict(self):
        old_gate = CallGate(10, 5)
        for _ in range(100):
            old_gate.update(random.randint(3, 5))
            old_gate.dec(random.randint(1, 3))
        new_gate = CallGate(**old_gate.as_dict())
        assert new_gate.gate_size == old_gate.gate_size
        assert new_gate.frame_step == old_gate.frame_step
        assert new_gate.gate_limit == old_gate.gate_limit
        assert new_gate.frame_limit == old_gate.frame_limit
        assert new_gate.frames == old_gate.frames
        assert new_gate.current_dt == old_gate.current_dt
        assert new_gate.data == old_gate.data
        assert new_gate.sum == old_gate.sum
        assert new_gate.timezone == old_gate.timezone


class TestSlidinggateIncAndDec:
    def test_increment(self, sliding_gate_2s_1s_no_limits):
        assert sliding_gate_2s_1s_no_limits.sum == 0
        sliding_gate_2s_1s_no_limits.update()
        assert sliding_gate_2s_1s_no_limits.sum == 1

    @pytest.mark.parametrize("value", [1, 2, 2**128])
    def test_increment_value(self, sliding_gate_2s_1s_no_limits, value):
        assert sliding_gate_2s_1s_no_limits.sum == 0
        sliding_gate_2s_1s_no_limits.update(value)
        assert sliding_gate_2s_1s_no_limits.sum == value

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
    def test_increment_value_fails_on_type(self, sliding_gate_2s_1s_no_limits, value):
        with pytest.raises(TypeError):
            assert sliding_gate_2s_1s_no_limits.update(value)

    @pytest.mark.parametrize("value", [0, -1, -2, -(2**128)])
    def test_increment_value_fails_on_zero_and_negative_values(self, sliding_gate_2s_1s_no_limits, value):
        with pytest.raises(ValueError):
            assert sliding_gate_2s_1s_no_limits.update(value)

    def test_decrement_raises_on_single_empty_frame(self, sliding_gate_2s_1s_no_limits):
        assert sliding_gate_2s_1s_no_limits.sum == 0
        assert len(sliding_gate_2s_1s_no_limits) == 0
        with pytest.raises(ValueError):
            sliding_gate_2s_1s_no_limits.dec()

    def test_decrement_raises_on_larger_value(self, sliding_gate_2s_1s_no_limits):
        assert sliding_gate_2s_1s_no_limits.sum == 0
        assert len(sliding_gate_2s_1s_no_limits) == 0
        sliding_gate_2s_1s_no_limits.update()
        with pytest.raises(ValueError):
            sliding_gate_2s_1s_no_limits.dec(random.randint(2, 2**128))

    def test_decrement_one(self, sliding_gate_2s_1s_no_limits):
        assert sliding_gate_2s_1s_no_limits.sum == 0
        assert len(sliding_gate_2s_1s_no_limits) == 0
        sliding_gate_2s_1s_no_limits.update()
        sliding_gate_2s_1s_no_limits.dec()
        assert sliding_gate_2s_1s_no_limits.sum == 0
        assert len(sliding_gate_2s_1s_no_limits) == 1

    @pytest.mark.xfail(reason="gate may have moved to another one frame while refreshing")
    def test_decrement_many_onetime(self):
        gate = CallGate(timedelta(seconds=1), timedelta(milliseconds=1))
        assert gate.sum == 0
        assert len(gate) == 0
        while not datetime.now(tz=gate.timezone).microsecond < 100000:
            continue
        increments = 1000
        for i in range(increments):
            gate.update()
        cur_val = gate.current_frame.value
        assert cur_val < increments
        dec_value = 999
        gate.dec(dec_value)
        assert gate.sum == 1
        assert gate.current_frame.value == 0
        assert gate.last_frame.value == 1
        assert all([gate.data[i] <= 1 for i in range(1, len(gate) - 1)])

    def test_decrement_many_onetime_but_a_bit_less(self):
        gate = CallGate(timedelta(seconds=1), timedelta(milliseconds=1))
        assert gate.sum == 0
        assert len(gate) == 0
        while not datetime.now(tz=gate.timezone).microsecond < 1000:
            continue
        increments = 1000
        for i in range(increments):
            gate.update()
        time.sleep(0.5)
        cur_val = gate.current_frame.value
        assert cur_val < increments
        assert gate.sum == 1000
        dec_value = 300
        gate.dec(dec_value)
        assert gate.sum == 700
        assert gate.current_frame.value == 0

    def test_decrement_many_onetime_raises_on_strict(self):
        gate = CallGate(timedelta(seconds=1), timedelta(milliseconds=500))
        assert gate.sum == 0
        assert len(gate) == 0
        while not datetime.now(tz=gate.timezone).microsecond < 100000:
            continue
        increments = 351000
        for i in range(increments):
            gate.update()
        time.sleep(0.5)
        with pytest.raises(ValueError):
            gate.dec(gate.sum - 1, strict=True)

    def test_decrement_many_onetime_raises_after_sleep(self):
        gate = CallGate(timedelta(seconds=1), timedelta(milliseconds=100))
        assert gate.sum == 0
        assert len(gate) == 0
        while not datetime.now(tz=gate.timezone).microsecond < 300000:
            continue
        for i in range(1000):
            gate.update()
            time.sleep(0.001)
        dec_value = 998
        time.sleep(0.5)
        gate.update()
        assert gate.sum < dec_value
        with pytest.raises(ValueError):
            assert gate.dec(dec_value)

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
    def test_decrement_value_fails_on_type(self, sliding_gate_2s_1s_no_limits, value):
        with pytest.raises(TypeError):
            assert sliding_gate_2s_1s_no_limits.dec(value)

    @pytest.mark.parametrize("value", [-1, -2, -(2**128)])
    def test_decrement_value_fails_on_negative_values(self, sliding_gate_2s_1s_no_limits, value):
        with pytest.raises(ValueError):
            assert sliding_gate_2s_1s_no_limits.dec(value)

    def test_increment_until_full(self, sliding_gate_2s_1s_no_limits):
        start = datetime.now()
        while datetime.now() < start + timedelta(seconds=2):
            sliding_gate_2s_1s_no_limits.update()
        assert len(sliding_gate_2s_1s_no_limits.data) == sliding_gate_2s_1s_no_limits.frames

    def test_increment_replaces_old_data(self, sliding_gate_2s_1s_no_limits):
        work = 1.6
        start = datetime.now()
        while datetime.now() < start + timedelta(seconds=work):
            sliding_gate_2s_1s_no_limits.update()
        first_cur_frame_time = sliding_gate_2s_1s_no_limits.current_frame.dt
        assert int(first_cur_frame_time.timestamp()) == int(datetime.now().timestamp())
        assert len(sliding_gate_2s_1s_no_limits.data) == sliding_gate_2s_1s_no_limits.frames
        win_sum = sliding_gate_2s_1s_no_limits.sum
        last_data = sliding_gate_2s_1s_no_limits.last_frame.value
        odata = sliding_gate_2s_1s_no_limits.data.copy()
        time.sleep(1)
        sliding_gate_2s_1s_no_limits.update()
        ndata = sliding_gate_2s_1s_no_limits.data.copy()
        assert first_cur_frame_time == sliding_gate_2s_1s_no_limits.last_frame.dt
        assert (
            round(sliding_gate_2s_1s_no_limits.current_frame.dt.timestamp())
            == round(first_cur_frame_time.timestamp()) + 1
        )
        assert sliding_gate_2s_1s_no_limits.sum == (win_sum - last_data + 1)

    def test_increment_replaces_old_data_after_long_sleep(self, sliding_gate_2s_1s_no_limits):
        start = datetime.now()
        while datetime.now() < start + timedelta(seconds=2):
            sliding_gate_2s_1s_no_limits.update()
        odata = deepcopy(sliding_gate_2s_1s_no_limits.data)
        win_sum = sliding_gate_2s_1s_no_limits.sum

        time.sleep(2)

        sliding_gate_2s_1s_no_limits.update()
        ndata = deepcopy(sliding_gate_2s_1s_no_limits.data)

        assert sliding_gate_2s_1s_no_limits.sum < win_sum
        assert sliding_gate_2s_1s_no_limits.sum == 1
        for idx in range(len(sliding_gate_2s_1s_no_limits)):
            assert odata[idx] != ndata[idx]

    def test_increment_replaces_old_data_after_short_sleep(self):
        sliding_gate = CallGate(timedelta(seconds=4), timedelta(seconds=1))
        start = datetime.now()
        while datetime.now() < start + timedelta(seconds=4):
            sliding_gate.update()
        dt = sliding_gate.current_dt
        win_sum = sliding_gate.sum
        odata = list(sliding_gate.data.copy())
        sleep = 2
        time.sleep(sleep)
        sliding_gate.update()
        ndata = list(sliding_gate.data)
        assert dt == sliding_gate.current_dt - sliding_gate.frame_step * sleep
        assert sliding_gate.data[sleep - 1] == 0
        assert odata[:sleep] == ndata[sleep:]
        assert sliding_gate.sum < win_sum

    def test_clean(self, sliding_gate_2s_1s_no_limits):
        assert len(sliding_gate_2s_1s_no_limits) == 0
        assert sliding_gate_2s_1s_no_limits.sum == 0
        assert sliding_gate_2s_1s_no_limits.data == []
        assert sliding_gate_2s_1s_no_limits.current_dt is None
        sliding_gate_2s_1s_no_limits.update()
        assert len(sliding_gate_2s_1s_no_limits) == 1
        assert sliding_gate_2s_1s_no_limits.sum == 1
        assert sliding_gate_2s_1s_no_limits.data == [1]
        assert isinstance(sliding_gate_2s_1s_no_limits.current_dt, datetime)
        sliding_gate_2s_1s_no_limits.clean()
        assert len(sliding_gate_2s_1s_no_limits) == 1
        assert sliding_gate_2s_1s_no_limits.sum == 0
        assert sliding_gate_2s_1s_no_limits.data == [0]
        assert sliding_gate_2s_1s_no_limits.current_dt is None


class TestSlidinggateLimits:
    def test_gate_limit(self, sliding_gate_gate_2s_1s_wl5):
        start = datetime.now()
        with pytest.raises(GateLimitError):
            while datetime.now() < start + timedelta(
                seconds=sliding_gate_gate_2s_1s_wl5.gate_size.total_seconds()
            ):
                sliding_gate_gate_2s_1s_wl5.update()

    def test_frame_limit(self, sliding_gate_frame_2s_1s_fl5):
        start = datetime.now()
        with pytest.raises(FrameLimitError):
            while datetime.now() < start + timedelta(
                seconds=sliding_gate_frame_2s_1s_fl5.gate_size.total_seconds()
            ):
                sliding_gate_frame_2s_1s_fl5.update()

    def test_both_limits(self):
        sliding_gate = CallGate(timedelta(seconds=4), timedelta(seconds=1), gate_limit=10, frame_limit=2)
        sliding_gate.update(5)
        with pytest.raises(FrameLimitError):
            sliding_gate.update()
        time.sleep(1.1)
        sliding_gate.update(5)
        assert sliding_gate.sum == 10
        time.sleep(1.1)
        with pytest.raises(GateLimitError):
            sliding_gate.update()


if __name__ == "__main__":
    pytest.main()
