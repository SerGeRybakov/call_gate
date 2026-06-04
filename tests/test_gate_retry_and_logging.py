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
