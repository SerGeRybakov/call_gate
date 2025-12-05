"""Test edge cases for CallGate configuration to improve coverage."""

import warnings

from datetime import timedelta

import pytest

from redis import Redis

from call_gate import CallGate, GateStorageType
from call_gate.errors import CallGateRedisConfigurationError, CallGateValueError
from tests.parameters import get_redis_kwargs, random_name


class TestCallGateConfigurationEdgeCases:
    """Test CallGate configuration edge cases to improve coverage."""

    def test_redis_client_with_kwargs_warning(self):
        """Test deprecation warning when both redis_client and kwargs provided."""
        try:
            redis_client = Redis(**get_redis_kwargs())
            redis_client.ping()  # Test connection
        except Exception:
            pytest.skip("Redis not available")

        # Test that warning is raised when both redis_client and kwargs are provided
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            gate = CallGate(
                random_name(),
                timedelta(seconds=1),
                timedelta(milliseconds=100),
                storage=GateStorageType.redis,
                redis_client=redis_client,
                host="localhost",  # This should trigger the warning
                port=6379,
            )

            # Should have raised a deprecation warning
            assert len(w) >= 1
            assert any("redis_client" in str(warning.message) for warning in w)
            assert any("kwargs" in str(warning.message) for warning in w)

        try:
            gate.clear()
        except Exception:
            pass

    def test_invalid_redis_client_type_error(self):
        """Test error when redis_client has wrong type (line 181)."""
        # Test with invalid redis_client type
        with pytest.raises(CallGateRedisConfigurationError, match="must be a pre-initialized"):
            CallGate(
                random_name(),
                timedelta(seconds=1),
                timedelta(milliseconds=100),
                storage=GateStorageType.redis,
                redis_client="invalid_client",  # Wrong type
            )

    def test_validate_timestamp_invalid_return_none(self):
        """Test _validate_and_set_timestamp raises exception for invalid timestamp."""
        gate = CallGate(random_name(), timedelta(seconds=1), timedelta(milliseconds=100))

        # Test with completely invalid timestamp that can't be parsed
        # This should raise CallGateValueError (line 253), not return None
        with pytest.raises(CallGateValueError, match="Timestamp must be an ISO string"):
            gate._validate_and_set_timestamp("completely_invalid_timestamp")

        try:
            gate.clear()
        except Exception:
            pass


if __name__ == "__main__":
    pytest.main()
