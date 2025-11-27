import random
import sys
import time

from copy import deepcopy
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import dateutil
import pytest

from call_gate import CallGate
from call_gate.errors import (
    CallGateValueError,
    FrameLimitError,
    FrameOverflowError,
    GateLimitError,
    GateOverflowError,
)
from tests.parameters import GITHUB_ACTIONS_REDIS_TIMEOUT, random_name, storages


@pytest.mark.timeout(GITHUB_ACTIONS_REDIS_TIMEOUT)
class TestCallGateInit:
    def test_empty_init_fails(self):
        with pytest.raises(TypeError):
            assert CallGate()

    @pytest.mark.parametrize("storage", storages)
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
    def test_init_success(self, gate_size, frame_step, storage):
        gate = CallGate(random_name(), gate_size, frame_step, storage=storage)
        assert gate is not None
        if not isinstance(gate_size, timedelta):
            gate_size = timedelta(seconds=gate_size)
        if not isinstance(frame_step, timedelta):
            frame_step = timedelta(seconds=frame_step)
        try:
            assert gate.gate_size == gate_size
            assert gate.frame_step == frame_step
            assert gate.frames == int(gate_size // frame_step)
            assert gate.gate_limit == 0
            assert gate.frame_limit == 0
            assert gate.data == [0] * gate.frames
            assert not gate.sum
            assert not gate.current_dt
            assert gate.timezone is None

            gate_dict = {
                "name": gate.name,
                "gate_size": gate_size.total_seconds(),
                "frame_step": frame_step.total_seconds(),
                "gate_limit": 0,
                "frame_limit": 0,
                "timezone": None,
                "storage": gate.storage,
                "_data": [0] * gate.frames,
                "_current_dt": None,
            }
            assert gate.as_dict() == gate_dict
            d = gate_dict.copy()
            d.pop("_data")
            d.pop("_current_dt")
            gate_repr = f"CallGate({', '.join(f'{k}={v}' for k, v in d.items())})"
            assert gate_repr == repr(gate)
            gate_str = str(gate.state)
            assert gate_str == str(gate)
            assert gate.current_frame.value == 0
            assert gate.last_frame.value == 0
        finally:
            gate.clear()

    @pytest.mark.parametrize("storage", storages)
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
    def test_init_fails_gate_size_and_or_granularity(self, gate_size, frame_step, storage):
        with pytest.raises(ValueError):
            assert CallGate(random_name(), gate_size, frame_step, storage=storage)

    @pytest.mark.parametrize("storage", storages)
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
    def test_init_fails_limits_wrong_type(self, gate_limit, frame_limit, storage):
        with pytest.raises(TypeError):
            assert CallGate(random_name(), 10, 5, gate_limit=gate_limit, frame_limit=frame_limit, storage=storage)

    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        "params",
        [
            dict(gate_limit=-1),
            dict(frame_limit=-2),
            dict(gate_limit=-10, frame_limit=-5),
        ],
    )
    def test_init_fails_limits_wrong_value(self, params, storage):
        with pytest.raises(ValueError):
            assert CallGate(random_name(), 10, 5, **params, storage=storage)

    @pytest.mark.parametrize("storage", storages)
    def test_init_fails_frame_limit_exceeds_gate_limit(self, storage):
        with pytest.raises(ValueError):
            assert CallGate(random_name(), 10, 5, gate_limit=1, frame_limit=2, storage=storage)

    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        ("gate_limit", "frame_limit"),
        [(0, 0), (1, 0), (2, 0), (0, 1), (0, 2), (2, 1)],
    )
    def test_init_gate_limit_frame_limit(self, gate_limit, frame_limit, storage):
        gate = CallGate(random_name(), 10, 5, gate_limit=gate_limit, frame_limit=frame_limit, storage=storage)
        assert gate.gate_limit == gate_limit
        assert gate.frame_limit == frame_limit
        assert gate.limits.frame_limit == frame_limit
        assert gate.limits.gate_limit == gate_limit

    @pytest.mark.parametrize("storage", ["a", 0, {"simple"}, ["redis"], ("shared",), "sipmle", "redsi", "shered"])
    def test_init_fails_on_storage_value(self, storage):
        with pytest.raises(ValueError):
            CallGate(random_name(), 10, 5, storage=storage)

    @pytest.mark.parametrize("storage", storages)
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
    def test_init_data(self, data, storage):
        gate = CallGate(random_name(), 10, 5, _data=data, storage=storage)

        expected = list(data)
        if len(expected) < gate.frames:
            expected = expected + [0] * (gate.frames - len(expected))
        else:
            expected = expected[: gate.frames]

        try:
            assert gate.data == expected
        finally:
            gate.clear()

    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        ("initial", "expected"),
        [
            ((), [0] * 10),
            ([], [0] * 10),
            ([1], [1] + [0] * 9),
            ((0,), [0] * 10),
            ([0, 1], [0, 1] + [0] * 8),
            ([1, 2], [1, 2] + [0] * 8),
            ([1] * 20, [1] * 10),
            ([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11], [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]),
            (None, [0] * 10),
        ],
    )
    def test_init_data_correct(self, initial, expected, storage):
        gate = CallGate(random_name(), 10, 1, _data=initial, storage=storage)
        try:
            assert gate.data == expected
        finally:
            gate.clear()

    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(
        "data",
        [
            ("1",),
            ["1"],
            [[1]],
            1,
            {1, 2},
            {0: 1},
            [1, None],
            [1, True],
            [1, False],
        ],
    )
    def test_init_data_fail_on_type(self, data, storage):
        with pytest.raises(TypeError):
            assert CallGate(random_name(), 10, 5, _data=data, storage=storage)

    @pytest.mark.parametrize("storage", storages)
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
            pytest.param(
                "20240101000000Z",
                marks=pytest.mark.xfail(sys.version_info < (3, 11), reason="Behaviour changed in 3.11", strict=True),
            ),
            pytest.param(
                "20240101 000000Z",
                marks=pytest.mark.xfail(sys.version_info < (3, 11), reason="Behaviour changed in 3.11", strict=True),
            ),
            pytest.param(
                "20240101-000000Z",
                marks=pytest.mark.xfail(sys.version_info < (3, 11), reason="Behaviour changed in 3.11", strict=True),
            ),
        ],
    )
    def test_init_timestamps(self, current_dt, storage):
        gate = CallGate(random_name(), 10, 5, _current_dt=current_dt, storage=storage)
        assert gate.current_dt == (dateutil.parser.parse(current_dt) if current_dt is not None else current_dt)

    @pytest.mark.parametrize("storage", storages)
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
            ["2024"],
            ["2024-1-1T00:00:00Z"],
            ["2024-01-01T00:00:00Z", "2024-01-01T00:00:01Z", "2024-01-01T00:00:02Z"],
            ("2024-01-01T00:00:00Z", "2024-01-01T00:00:01Z", "2024-01-01T00:00:02Z"),
        ],
    )
    def test_init_timestamps_fail_on_type(self, current_dt, storage):
        with pytest.raises(TypeError):
            CallGate(random_name(), 10, 5, _current_dt=current_dt, storage=storage)

    @pytest.mark.parametrize("storage", storages)
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
            pytest.param(
                "20240101000000Z",
                marks=pytest.mark.xfail(sys.version_info >= (3, 11), reason="Behaviour changed in 3.11", strict=True),
            ),
            pytest.param(
                "20240101 000000Z",
                marks=pytest.mark.xfail(sys.version_info >= (3, 11), reason="Behaviour changed in 3.11", strict=True),
            ),
            pytest.param(
                "20240101-000000Z",
                marks=pytest.mark.xfail(sys.version_info >= (3, 11), reason="Behaviour changed in 3.11", strict=True),
            ),
        ],
    )
    def test_init_timestamps_fail_on_value(self, current_dt, storage):
        with pytest.raises(ValueError):
            assert CallGate(random_name(), 10, 5, _current_dt=current_dt, storage=storage)

    @pytest.mark.parametrize("storage", storages)
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
    def test_init_sum_fail_on_type(self, sum, storage):
        with pytest.raises(TypeError):
            assert CallGate(random_name(), 5, sum=sum, storage=storage)

    @pytest.mark.parametrize("storage", storages)
    def test_init_from_dict(self, storage):
        old_gate = CallGate(random_name(), 10, 5, storage=storage)
        for _ in range(100):
            old_gate.update(random.randint(3, 5))
        new_gate = CallGate(**old_gate.as_dict())
        try:
            assert new_gate.gate_size == old_gate.gate_size
            assert new_gate.frame_step == old_gate.frame_step
            assert new_gate.gate_limit == old_gate.gate_limit
            assert new_gate.frame_limit == old_gate.frame_limit
            assert new_gate.frames == old_gate.frames
            assert new_gate.current_dt == old_gate.current_dt
            assert new_gate.data == old_gate.data
            assert new_gate.sum == old_gate.sum
            assert new_gate.timezone == old_gate.timezone
            assert new_gate.storage == old_gate.storage
        finally:
            old_gate.clear()
            new_gate.clear()

    @pytest.mark.parametrize(
        "tz",
        [
            None,
            "UTC",
            "Europe/London",
            "Asia/Tokyo",
            "Africa/Cairo",
            "Australia/Melbourne",
            "America/Chicago",
        ],
    )
    def test_timezone(self, tz):
        gate = CallGate(random_name(), 2, 1, timezone=tz)
        gate.update()
        gate_dict = gate.as_dict()
        try:
            if tz is None:
                assert gate.timezone is None
                assert gate_dict["timezone"] is None
                assert gate.current_dt.tzinfo is None
                assert gate.current_frame.dt.tzinfo is None
            else:
                assert gate.timezone == ZoneInfo(tz)
                assert gate_dict["timezone"] == tz
                assert gate.current_dt.tzinfo == ZoneInfo(tz)
                assert gate.current_frame.dt.tzinfo == ZoneInfo(tz)
        finally:
            gate.clear()


@pytest.mark.timeout(GITHUB_ACTIONS_REDIS_TIMEOUT)
class TestCallGateUpdate:
    def test_increment(self, call_gate_2s_1s_no_limits):
        try:
            assert call_gate_2s_1s_no_limits.sum == 0
            call_gate_2s_1s_no_limits.update()
            assert call_gate_2s_1s_no_limits.sum == 1
        finally:
            call_gate_2s_1s_no_limits.clear()

    @pytest.mark.parametrize("value", [1, 2, 2**53 - 1, 2**64 - 1])
    def test_increment_value(self, call_gate_2s_1s_no_limits, value):
        """Normally all storages support values up to 2**64-1.

        But redis supports up to 2**53-1 only because it uses Lua 5.1.
        Lua 5.1 works with numbers as `double64` bit floating point
        numbers in IEEE 754 standard.

        This means that all integers up to 2**53-1 can be represented
        exactly, and when this threshold is exceeded, precision is lost.
        """
        try:
            assert call_gate_2s_1s_no_limits.sum == 0
            call_gate_2s_1s_no_limits.update(value)
            if value == 2**64 - 1 and call_gate_2s_1s_no_limits.storage == "redis":
                assert call_gate_2s_1s_no_limits.sum != value
            else:
                assert call_gate_2s_1s_no_limits.sum == value
        finally:
            call_gate_2s_1s_no_limits.clear()

    @pytest.mark.parametrize(
        "value",
        [
            "1",
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
    def test_increment_value_fails_on_type(self, call_gate_2s_1s_no_limits, value):
        try:
            with pytest.raises(TypeError):
                assert call_gate_2s_1s_no_limits.update(value)
        finally:
            call_gate_2s_1s_no_limits.clear()

    @pytest.mark.parametrize("throw", [True, False])
    @pytest.mark.parametrize("value", [-1, -2, -(2**64 - 1)])
    def test_increment_value_fails_on_negative_sum(self, call_gate_2s_1s_no_limits, value, throw):
        try:
            with pytest.raises(GateOverflowError):
                assert call_gate_2s_1s_no_limits.update(value, throw=throw)
        finally:
            call_gate_2s_1s_no_limits.clear()

    @pytest.mark.parametrize("throw", [True, False])
    def test_increment_value_fails_on_negative_frame(self, call_gate_2s_1s_no_limits, throw):
        for _ in range(2):
            call_gate_2s_1s_no_limits.update()
        time.sleep(1)
        try:
            with pytest.raises(FrameOverflowError):
                assert call_gate_2s_1s_no_limits.update(-1, throw=throw)
        finally:
            call_gate_2s_1s_no_limits.clear()

    def test_increment_until_full(self, call_gate_2s_1s_no_limits):
        start = datetime.now()
        try:
            while datetime.now() < start + timedelta(seconds=2):
                call_gate_2s_1s_no_limits.update()
            assert len(call_gate_2s_1s_no_limits.data) == call_gate_2s_1s_no_limits.frames
        finally:
            call_gate_2s_1s_no_limits.clear()

    @pytest.mark.flaky(retries=3, delay=1)
    def test_increment_replaces_old_data(self, call_gate_2s_1s_no_limits):
        work = 1.6
        start = datetime.now()
        while datetime.now() < start + timedelta(seconds=work):
            call_gate_2s_1s_no_limits.update()
        first_cur_frame_time = call_gate_2s_1s_no_limits.current_frame.dt
        try:
            assert int(first_cur_frame_time.timestamp()) == int(datetime.now().timestamp())
            assert len(call_gate_2s_1s_no_limits.data) == call_gate_2s_1s_no_limits.frames
            gate_sum = call_gate_2s_1s_no_limits.sum
            last_data = call_gate_2s_1s_no_limits.last_frame.value
            time.sleep(1)
            call_gate_2s_1s_no_limits.update()
            assert first_cur_frame_time == call_gate_2s_1s_no_limits.last_frame.dt
            assert (
                round(call_gate_2s_1s_no_limits.current_frame.dt.timestamp())
                == round(first_cur_frame_time.timestamp()) + 1
            )
            assert call_gate_2s_1s_no_limits.sum == (gate_sum - last_data + 1)
        finally:
            call_gate_2s_1s_no_limits.clear()

    def test_increment_replaces_old_data_after_long_sleep(self, call_gate_2s_1s_no_limits):
        start = datetime.now()
        while datetime.now() < start + timedelta(seconds=2):
            call_gate_2s_1s_no_limits.update()
        odata = deepcopy(call_gate_2s_1s_no_limits.data)
        gate_sum = call_gate_2s_1s_no_limits.sum

        time.sleep(2)

        call_gate_2s_1s_no_limits.update()
        ndata = deepcopy(call_gate_2s_1s_no_limits.data)
        try:
            assert call_gate_2s_1s_no_limits.sum < gate_sum
            assert call_gate_2s_1s_no_limits.sum == 1
            for idx in range(len(call_gate_2s_1s_no_limits)):
                assert odata[idx] != ndata[idx]
        finally:
            call_gate_2s_1s_no_limits.clear()

    def test_increment_replaces_old_data_after_short_sleep(self):
        call_gate = CallGate(random_name(), timedelta(seconds=4), timedelta(seconds=1))
        start = datetime.now()
        while datetime.now() < start + timedelta(seconds=4):
            call_gate.update()
        dt = call_gate.current_dt
        gate_sum = call_gate.sum
        odata = list(call_gate.data.copy())
        sleep = 2
        time.sleep(sleep)
        call_gate.update()
        ndata = list(call_gate.data)
        try:
            assert dt == call_gate.current_dt - call_gate.frame_step * sleep
            assert call_gate.data[sleep - 1] == 0
            assert odata[:sleep] == ndata[sleep:]
            assert call_gate.sum < gate_sum
        finally:
            call_gate.clear()

    def test_clear(self, call_gate_2s_1s_no_limits):
        assert len(call_gate_2s_1s_no_limits) == 2
        assert call_gate_2s_1s_no_limits.sum == 0
        assert call_gate_2s_1s_no_limits.data == [0, 0]
        assert call_gate_2s_1s_no_limits.current_dt is None
        call_gate_2s_1s_no_limits.update()
        assert call_gate_2s_1s_no_limits.sum == 1
        assert call_gate_2s_1s_no_limits.data == [1, 0]
        assert isinstance(call_gate_2s_1s_no_limits.current_dt, datetime)
        call_gate_2s_1s_no_limits.clear()
        assert call_gate_2s_1s_no_limits.sum == 0
        assert call_gate_2s_1s_no_limits.data == [0, 0]
        assert call_gate_2s_1s_no_limits.current_dt is None

    def test_update_zero_does_nothing(self, call_gate_2s_1s_no_limits):
        initial_sum = call_gate_2s_1s_no_limits.sum
        call_gate_2s_1s_no_limits.update(0)
        assert call_gate_2s_1s_no_limits.sum == initial_sum


@pytest.mark.timeout(GITHUB_ACTIONS_REDIS_TIMEOUT)
class TestCallGateLimits:
    def test_gate_limit(self, call_gate_2s_1s_gl5):
        start = datetime.now()
        try:
            with pytest.raises(GateLimitError):
                while datetime.now() < start + timedelta(seconds=call_gate_2s_1s_gl5.gate_size.total_seconds()):
                    call_gate_2s_1s_gl5.update(throw=True)
        finally:
            call_gate_2s_1s_gl5.clear()

    def test_frame_limit(self, call_gate_2s_1s_fl5):
        start = datetime.now()
        try:
            with pytest.raises(FrameLimitError):
                while datetime.now() < start + timedelta(seconds=call_gate_2s_1s_fl5.gate_size.total_seconds()):
                    call_gate_2s_1s_fl5.update(throw=True)
        finally:
            call_gate_2s_1s_fl5.clear()

    def test_both_limits(self):
        call_gate = CallGate(random_name(), timedelta(seconds=4), timedelta(seconds=1), gate_limit=4, frame_limit=2)
        call_gate.update(2)
        try:
            with pytest.raises(FrameLimitError):
                call_gate.update(throw=True)
            time.sleep(1.1)
            call_gate.update(2)
            assert call_gate.sum == call_gate.gate_limit
            time.sleep(1.1)
            with pytest.raises(GateLimitError):
                call_gate.update(throw=True)
        finally:
            call_gate.clear()

    @pytest.mark.parametrize("storage", storages)
    def test_check_limits_gate(self, storage):
        gate = CallGate(
            random_name(),
            timedelta(seconds=1),
            timedelta(milliseconds=100),
            gate_limit=100,
            frame_limit=10,
            storage=storage,
        )

        while gate.sum < gate.gate_limit:
            gate.update()

        try:
            with pytest.raises(GateLimitError):
                gate.check_limits()
        finally:
            gate.clear()

    @pytest.mark.parametrize("storage", storages)
    def test_check_limits_frame(self, storage):
        gate = CallGate(
            random_name(),
            timedelta(seconds=1),
            timedelta(milliseconds=100),
            gate_limit=100,
            frame_limit=10,
            storage=storage,
        )

        while gate.current_frame.value < gate.frame_limit:
            gate.update()

        try:
            with pytest.raises(FrameLimitError):
                gate.check_limits()
        finally:
            gate.clear()


@pytest.mark.timeout(GITHUB_ACTIONS_REDIS_TIMEOUT)
class TestStorageEdgeCases:
    """Test edge cases for all storage types to improve coverage."""

    @pytest.mark.parametrize("storage", storages)
    def test_slide_negative_value_error(self, storage):
        """Test that slide() with negative values raises CallGateValueError."""
        gate = CallGate(random_name(), timedelta(seconds=2), timedelta(seconds=1), storage=storage)
        try:
            # Test n < 1 raises error by calling slide directly on storage
            # This is a low-level test of the storage implementation
            with pytest.raises(CallGateValueError, match="Value must be >= 1"):
                gate._data.slide(-1)

            with pytest.raises(CallGateValueError, match="Value must be >= 1"):
                gate._data.slide(0)
        finally:
            gate.clear()

    @pytest.mark.parametrize("storage", storages)
    def test_slide_capacity_or_more_calls_clear(self, storage):
        """Test that slide() with n >= capacity calls clear()."""
        # Create gate with very short time window to trigger sliding
        gate = CallGate(random_name(), timedelta(milliseconds=100), timedelta(milliseconds=10), storage=storage)
        try:
            # Add some data
            gate.update(10)
            gate.update(5)
            initial_sum = gate.sum
            assert initial_sum > 0

            # Wait for time window to pass completely (should trigger slide >= capacity)
            time.sleep(0.15)  # Wait longer than gate window

            # Any new update should trigger sliding that clears old data
            gate.update(1)

            # After sliding, only the new update should remain
            assert gate.sum == 1

        finally:
            gate.clear()

    @pytest.mark.parametrize("storage", storages)
    def test_storage_bool_method(self, storage):
        """Test BaseStorage __bool__ method behavior."""
        gate = CallGate(random_name(), timedelta(seconds=2), timedelta(seconds=1), storage=storage)
        try:
            # Initially sum is 0, so storage should be False
            assert not bool(gate._data)
            assert gate._data.__bool__() is False

            # After adding data, storage should be True
            gate.update(1)
            assert bool(gate._data)
            assert gate._data.__bool__() is True

            # After clearing, should be False again
            gate.clear()
            assert not bool(gate._data)
            assert gate._data.__bool__() is False
        finally:
            gate.clear()

    @pytest.mark.parametrize("storage", storages)
    def test_gate_init_with_none_timestamp(self, storage):
        """Test CallGate initialization with explicit None timestamp to cover line 177."""
        gate = CallGate(
            random_name(),
            timedelta(seconds=2),
            timedelta(seconds=1),
            storage=storage,
            _current_dt=None,  # Explicitly pass None to trigger line 177
        )
        try:
            # Should initialize successfully with None timestamp
            assert gate._current_dt is None or isinstance(gate._current_dt, datetime)
        finally:
            gate.clear()


if __name__ == "__main__":
    pytest.main()
