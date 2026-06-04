import logging
import pickle
import threading

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from call_gate import CallGate
from call_gate.errors import CallGateTypeError, CallGateValueError, FrameLimitError, GateLimitError
from tests.parameters import random_name


class TestGateLimitMaxWaitFramesValidation:
    def test_negative_raises(self):
        gate = CallGate(random_name(), 10, 1)
        with pytest.raises(CallGateValueError):
            gate.update(gate_limit_max_wait_frames=-1)

    def test_non_int_raises(self):
        gate = CallGate(random_name(), 10, 1)
        with pytest.raises(CallGateTypeError):
            gate.update(gate_limit_max_wait_frames=1.5)  # type: ignore[arg-type]

    def test_call_validates(self):
        gate = CallGate(random_name(), 10, 1)
        with pytest.raises(CallGateValueError):
            gate(gate_limit_max_wait_frames=-1)


class TestLogLevelInit:
    def test_invalid_log_level_string(self):
        with pytest.raises(CallGateValueError):
            CallGate(random_name(), 10, 1, log_level="TRACE")

    def test_default_has_no_handler(self):
        gate = CallGate(random_name(), 10, 1)
        assert len(gate._logger.handlers) == 0
        gate.clear()

    def test_log_level_none_has_no_handler(self):
        gate = CallGate(random_name(), 10, 1, log_level=None)
        assert gate._logger.name.startswith("CallGate.")
        assert len(gate._logger.handlers) == 0
        gate.clear()

    def test_log_level_accepts_logging_constant(self):
        gate = CallGate(random_name(), 10, 1, log_level=logging.DEBUG)
        assert len(gate._logger.handlers) == 1
        assert gate._logger.level == logging.DEBUG
        assert gate._logger.handlers[0].level == logging.DEBUG
        gate.clear()


class TestUpdateValueExceedsLimits:
    def test_value_exceeds_gate_limit_raises_immediately(self):
        gate = CallGate(random_name(), 10, 1, gate_limit=10)
        with pytest.raises(GateLimitError, match="exceeds the set gate limit"):
            gate.update(11)
        gate.clear()

    def test_value_exceeds_gate_limit_no_retry_when_throw_false(self):
        gate = CallGate(random_name(), 10, 1, gate_limit=10)
        with patch("call_gate.gate.time.sleep") as sleep_mock:
            with pytest.raises(GateLimitError, match="exceeds the set gate limit"):
                gate.update(11, throw=False)
        sleep_mock.assert_not_called()
        gate.clear()

    def test_value_exceeds_frame_limit_raises_immediately(self):
        gate = CallGate(random_name(), 10, 1, frame_limit=5)
        with pytest.raises(FrameLimitError, match="exceeds the set frame limit"):
            gate.update(6)
        gate.clear()

    def test_zero_limits_skip_value_check(self):
        gate = CallGate(random_name(), 10, 1, gate_limit=0, frame_limit=0)
        gate.update(100)
        assert gate.sum == 100
        gate.clear()


class TestUpdateRetryBudget:
    def _gate_at_gate_limit(self) -> CallGate:
        gate = CallGate(random_name(), 10, 1, gate_limit=1)
        gate.update(1)
        assert gate.sum == 1
        return gate

    def test_raises_after_n_waits(self):
        gate = self._gate_at_gate_limit()
        with patch("call_gate.gate.time.sleep"):
            with pytest.raises(GateLimitError):
                gate.update(gate_limit_max_wait_frames=2)
        gate.clear()

    def test_default_zero_uses_frames_budget(self):
        gate = CallGate(random_name(), 4, 1, gate_limit=1)
        gate.update(1)
        attempts = {"n": 0}

        def atomic(*_args, **_kwargs):
            attempts["n"] += 1
            raise GateLimitError("limit", gate)

        with patch.object(gate._data, "atomic_update", side_effect=atomic):
            with patch("call_gate.gate.time.sleep"):
                with pytest.raises(GateLimitError):
                    gate.update(gate_limit_max_wait_frames=0)
        assert attempts["n"] == gate.frames + 1
        gate.clear()

    def test_frame_and_gate_limits_share_budget(self):
        gate = CallGate(random_name(), 10, 1, gate_limit=100, frame_limit=1)
        gate.update(1)
        sequence = [FrameLimitError("frame", gate), GateLimitError("gate", gate), GateLimitError("frame", gate)]

        def atomic(*_args, **_kwargs):
            exc = sequence.pop(0)
            raise exc

        with patch.object(gate._data, "atomic_update", side_effect=atomic):
            with patch("call_gate.gate.time.sleep"):
                with pytest.raises(GateLimitError):
                    gate.update(gate_limit_max_wait_frames=2)
        gate.clear()

    def test_gate_limit_sleeps_one_frame_step_per_wait(self):
        gate = CallGate(random_name(), 4, 1, gate_limit=1)
        gate.update(1)
        sleeps: list[float] = []

        def atomic(*_args, **_kwargs):
            raise GateLimitError("limit", gate)

        with patch.object(gate._data, "atomic_update", side_effect=atomic):
            with patch("call_gate.gate.time.sleep", side_effect=lambda s: sleeps.append(s)):
                with pytest.raises(GateLimitError):
                    gate.update(gate_limit_max_wait_frames=0)
        assert len(sleeps) == gate.frames
        assert all(s == gate.frame_step.total_seconds() for s in sleeps)
        gate.clear()

    def test_raises_after_frame_limit_waits_exhausted(self, capsys):
        gate = CallGate(random_name(), 10, 1, frame_limit=1, log_level="WARNING")
        gate.update(1)
        with patch("call_gate.gate.time.sleep"):
            with pytest.raises(FrameLimitError):
                gate.update(1, throw=False, gate_limit_max_wait_frames=1)
        assert "raising" in capsys.readouterr().err
        gate.clear()

    def test_succeeds_after_waits(self):
        gate = CallGate(random_name(), 10, 1, gate_limit=5)
        calls = {"n": 0}
        real_atomic = gate._data.atomic_update

        def atomic(value, frame_limit, gate_limit):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise GateLimitError("limit", gate)
            return real_atomic(value, frame_limit, gate_limit)

        with patch.object(gate._data, "atomic_update", side_effect=atomic):
            with patch("call_gate.gate.time.sleep"):
                gate.update(gate_limit_max_wait_frames=3)
        assert calls["n"] == 3
        gate.clear()


class TestUpdateRetryLogging:
    def test_debug_on_retry(self, capsys):
        gate = CallGate(random_name(), 10, 1, gate_limit=1, log_level="DEBUG")
        gate.update(1)
        with patch("call_gate.gate.time.sleep"):
            with pytest.raises(GateLimitError):
                gate.update(gate_limit_max_wait_frames=1)
        assert "waits_left" in capsys.readouterr().err
        gate.clear()

    def test_warning_before_raise(self, capsys):
        gate = CallGate(random_name(), 10, 1, gate_limit=1, log_level="WARNING")
        gate.update(1)
        with patch("call_gate.gate.time.sleep"):
            with pytest.raises(GateLimitError):
                gate.update(gate_limit_max_wait_frames=0)
        assert "raising" in capsys.readouterr().err
        gate.clear()

    def test_info_after_successful_waits(self, capsys):
        gate = CallGate(random_name(), 10, 1, gate_limit=5, log_level="INFO")
        calls = {"n": 0}
        real_atomic = gate._data.atomic_update

        def atomic(value, frame_limit, gate_limit):
            calls["n"] += 1
            if calls["n"] == 1:
                raise GateLimitError("limit", gate)
            return real_atomic(value, frame_limit, gate_limit)

        with patch.object(gate._data, "atomic_update", side_effect=atomic):
            with patch("call_gate.gate.time.sleep"):
                gate.update(gate_limit_max_wait_frames=2)
        assert "Update succeeded after" in capsys.readouterr().err
        gate.clear()

    def test_info_on_immediate_success(self, capsys):
        gate = CallGate(random_name(), 10, 1, gate_limit=10, log_level="INFO")
        gate.update(2)
        out = capsys.readouterr().err
        assert "Update succeeded, value=2, sum=2" in out
        assert "after" not in out
        gate.clear()


class TestSugarRetryPropagation:
    def test_decorator_passes_max_wait(self):
        gate = CallGate(random_name(), 10, 1, gate_limit=1)
        gate.update(1)

        @gate(1, gate_limit_max_wait_frames=1)
        def fn():
            pass

        with patch("call_gate.gate.time.sleep"):
            with pytest.raises(GateLimitError):
                fn()
        gate.clear()

    def test_context_manager_passes_max_wait(self):
        gate = CallGate(random_name(), 10, 1, gate_limit=1)
        gate.update(1)
        with patch("call_gate.gate.time.sleep"):
            with pytest.raises(GateLimitError):
                with gate(1, gate_limit_max_wait_frames=1):
                    pass
        gate.clear()

    @pytest.mark.asyncio
    async def test_async_context_manager_passes_max_wait(self):
        gate = CallGate(random_name(), 10, 1, gate_limit=1)
        await gate.update(1)
        with patch("call_gate.gate.time.sleep"):
            with pytest.raises(GateLimitError):
                async with gate(1, gate_limit_max_wait_frames=1):
                    pass
        await gate.clear()


class TestLoggerInit:
    def test_logger_is_instance_attribute(self):
        gate = CallGate(random_name(), 10, 1)
        try:
            assert gate._logger.name == f"CallGate.{gate.name}"
            assert gate._logger is logging.getLogger(f"CallGate.{gate.name}")
        finally:
            gate.clear()

    def test_log_level_string_name(self):
        gate = CallGate(random_name(), 10, 1, log_level="INFO")
        try:
            assert gate._logger.level == logging.INFO
            assert len(gate._logger.handlers) == 1
        finally:
            gate.clear()

    def test_custom_log_format(self, capsys):
        custom = "GATE %(message)s"
        gate = CallGate(random_name(), 10, 1, log_level="INFO", log_format=custom)
        try:
            gate.update(1)
            assert "GATE Update succeeded" in capsys.readouterr().err
        finally:
            gate.clear()

    def test_pickle_restores_logger(self):
        gate = CallGate(random_name(), 10, 1, log_level=logging.INFO)
        try:
            gate.update(1)
            roundtrip = pickle.loads(pickle.dumps(gate))  # noqa: S301
            assert roundtrip._logger.name == gate._logger.name
            assert roundtrip._logger is logging.getLogger(f"CallGate.{gate.name}")
            roundtrip.update(1)
        finally:
            gate.clear()


class TestEmitGateLog:
    def test_none_event_is_noop(self):
        gate = CallGate(random_name(), 10, 1, log_level="DEBUG")
        try:
            gate._emit_gate_log(None)
        finally:
            gate.clear()

    def test_skips_when_level_disabled(self, capsys):
        gate = CallGate(random_name(), 10, 1, log_level="WARNING")
        try:
            gate._emit_gate_log(("debug", "hidden %s", (1,)))
            assert capsys.readouterr().err == ""
        finally:
            gate.clear()

    def test_emits_when_level_enabled(self, capsys):
        gate = CallGate(random_name(), 10, 1, log_level="DEBUG")
        try:
            gate._emit_gate_log(("debug", "visible %s", (42,)))
            assert "visible 42" in capsys.readouterr().err
        finally:
            gate.clear()


class TestDeferredRefreshLogging:
    def _time_patched_gate(self, *, log_level: str = "DEBUG"):
        frame_step = timedelta(seconds=1)
        base = datetime(2026, 6, 1, 12, 0, 0)
        now = {"t": base}
        gate = CallGate(random_name(), timedelta(seconds=4), frame_step, log_level=log_level)

        def fake_current_step(_self):
            remainder = now["t"].timestamp() % frame_step.total_seconds()
            return now["t"] - timedelta(seconds=remainder)

        return gate, now, frame_step, fake_current_step

    def test_refresh_frames_unlocked_returns_none_on_first_frame(self):
        gate = CallGate(random_name(), 10, 1)
        try:
            with gate._lock:
                assert gate._refresh_frames_unlocked() is None
        finally:
            gate.clear()

    def test_refresh_frames_unlocked_returns_none_when_no_diff(self):
        gate, _now, _frame_step, fake_step = self._time_patched_gate()
        try:
            with patch.object(CallGate, "_current_step", fake_step):
                gate.update(1)
                with gate._lock:
                    assert gate._refresh_frames_unlocked() is None
        finally:
            gate.clear()

    def test_refresh_frames_logs_slide(self, capsys):
        gate, now, frame_step, fake_step = self._time_patched_gate(log_level="DEBUG")
        try:
            with patch.object(CallGate, "_current_step", fake_step):
                gate.update(5)
                now["t"] = now["t"] + frame_step
                gate._refresh_frames()
            assert "Sliding window by 1 frame(s)" in capsys.readouterr().err
        finally:
            gate.clear()

    def test_refresh_frames_logs_clear(self, capsys):
        gate, now, frame_step, fake_step = self._time_patched_gate(log_level="INFO")
        try:
            with patch.object(CallGate, "_current_step", fake_step):
                gate.update(5)
                now["t"] = now["t"] + frame_step * gate.frames
                gate._refresh_frames()
            assert "Clearing sliding window" in capsys.readouterr().err
        finally:
            gate.clear()

    def test_check_limits_emits_refresh_log(self, capsys):
        gate, now, frame_step, fake_step = self._time_patched_gate(log_level="DEBUG")
        try:
            with patch.object(CallGate, "_current_step", fake_step):
                gate.update(1)
                now["t"] = now["t"] + frame_step
                gate.check_limits()
            assert "Sliding window by 1 frame(s)" in capsys.readouterr().err
        finally:
            gate.clear()

    def test_check_limits_raises_gate_limit(self):
        gate = CallGate(random_name(), 10, 1, gate_limit=1)
        try:
            gate.update(1)
            with pytest.raises(GateLimitError, match="Gate limit is reached"):
                gate.check_limits()
        finally:
            gate.clear()

    def test_check_limits_raises_frame_limit(self):
        gate = CallGate(random_name(), 10, 1, frame_limit=1)
        try:
            gate.update(1)
            with pytest.raises(FrameLimitError, match="Frame limit is reached"):
                gate.check_limits()
        finally:
            gate.clear()

    def test_throw_true_emits_refresh_log(self, capsys):
        gate, now, frame_step, fake_step = self._time_patched_gate(log_level="DEBUG")
        try:
            with patch.object(CallGate, "_current_step", fake_step):
                gate.update(1)
                now["t"] = now["t"] + frame_step
                gate.update(1, throw=True)
            assert "Sliding window by 1 frame(s)" in capsys.readouterr().err
        finally:
            gate.clear()


class TestLoggingOutsideLocks:
    class _ReentrantHandler(logging.Handler):
        def __init__(self, gate: CallGate):
            super().__init__()
            self.gate = gate

        def emit(self, record) -> None:
            self.gate.update(0)

    def test_throw_true_reraises_special_call_gate_error(self):
        gate = CallGate(random_name(), 10, 1, log_level="INFO")
        try:
            with patch.object(
                gate._data,
                "atomic_update",
                side_effect=FrameLimitError("frame", gate),
            ):
                with pytest.raises(FrameLimitError):
                    gate.update(1, throw=True)
        finally:
            gate.clear()

    def test_throw_true_success_log_survives_reentrant_handler(self):
        gate = CallGate(random_name(), 10, 1, gate_limit=10, log_level="INFO")
        handler = self._ReentrantHandler(gate)
        gate._logger.addHandler(handler)
        gate._logger.propagate = False
        try:
            gate.update(1, throw=True)
            assert gate.sum == 1
        finally:
            gate._logger.removeHandler(handler)
            gate.clear()

    def test_retry_debug_log_survives_reentrant_handler(self):
        gate = CallGate(random_name(), 10, 1, gate_limit=1, log_level="DEBUG")
        handler = self._ReentrantHandler(gate)
        gate._logger.addHandler(handler)
        gate._logger.propagate = False
        gate.update(1)
        try:
            with patch("call_gate.gate.time.sleep"):
                with pytest.raises(GateLimitError):
                    gate.update(gate_limit_max_wait_frames=1)
        finally:
            gate._logger.removeHandler(handler)
            gate.clear()

    def test_throw_false_does_not_hold_rlock_during_sleep(self):
        gate = CallGate(random_name(), 10, 1, gate_limit=1)
        gate.update(1)
        in_sleep = threading.Event()
        release_sleep = threading.Event()
        acquired_during_sleep = {"ok": False}

        def atomic(*_args, **_kwargs):
            raise GateLimitError("limit", gate)

        def sleep_hook(_seconds):
            in_sleep.set()
            acquired_during_sleep["ok"] = gate._rlock.acquire(timeout=0.5)
            if acquired_during_sleep["ok"]:
                gate._rlock.release()
            release_sleep.set()

        try:
            with patch.object(gate._data, "atomic_update", side_effect=atomic):
                with patch("call_gate.gate.time.sleep", side_effect=sleep_hook):
                    with pytest.raises(GateLimitError):
                        gate.update(gate_limit_max_wait_frames=1)
            assert in_sleep.wait(timeout=1)
            assert acquired_during_sleep["ok"]
        finally:
            gate.clear()


class TestUpdateEarlyReturn:
    def test_zero_value_skips_logging(self, capsys):
        gate = CallGate(random_name(), 10, 1, log_level="INFO")
        try:
            gate.update(0)
            assert capsys.readouterr().err == ""
        finally:
            gate.clear()
