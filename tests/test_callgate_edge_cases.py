"""Test edge cases for CallGate configuration to improve coverage."""

from datetime import timedelta

import pytest

from redis import Redis

from call_gate import CallGate, GateStorageType
from call_gate.errors import (
    CallGateRedisConfigurationError,
    CallGateValueError,
)
from tests.parameters import get_redis_kwargs, random_name


class TestCallGateConfigurationEdgeCases:
    """Test CallGate configuration edge cases to improve coverage."""

    def test_redis_client_with_invalid_kwargs(self):
        """Test invalid kwargs (v1.x compatibility) are rejected."""
        redis_client = Redis(**get_redis_kwargs())
        redis_client.ping()  # Test connection

        # In v2.0+, host and port are not accepted parameters
        with pytest.raises(TypeError, match="unexpected keyword argument"):
            CallGate(
                random_name(),
                timedelta(seconds=1),
                timedelta(milliseconds=100),
                storage=GateStorageType.redis,
                redis_client=redis_client,
                host="localhost",  # This should cause TypeError
                port=6379,
            )

    def test_invalid_redis_client_type_error(self):
        """Test error when redis_client has wrong type."""
        # Test with invalid redis_client type
        with pytest.raises(
            CallGateRedisConfigurationError,
            match="must be a pre-initialized",
        ):
            CallGate(
                random_name(),
                timedelta(seconds=1),
                timedelta(milliseconds=100),
                storage=GateStorageType.redis,
                redis_client="invalid_client",  # Wrong type
            )

    def test_validate_timestamp_invalid_return_none(self):
        """Test _validate_and_set_timestamp raises exception."""
        gate = CallGate(
            random_name(),
            timedelta(seconds=1),
            timedelta(milliseconds=100),
        )

        # Test with completely invalid timestamp
        with pytest.raises(CallGateValueError, match="Timestamp must be an ISO string"):
            gate._validate_and_set_timestamp("completely_invalid_timestamp")

        try:
            gate.clear()
        except Exception:
            pass

    def test_validate_and_set_timestamp_with_none(self):
        """Test _validate_and_set_timestamp returns None."""
        # Test with None - should return None
        result = CallGate._validate_and_set_timestamp(None)
        assert result is None

    def test_redis_storage_without_client_raises_error(self):
        """Test selecting redis storage without client raises error."""
        # Test with GateStorageType.redis
        with pytest.raises(
            CallGateRedisConfigurationError,
            match="Redis storage requires a pre-initialized",
        ):
            CallGate(
                random_name(),
                timedelta(seconds=1),
                timedelta(milliseconds=100),
                storage=GateStorageType.redis,
            )

        # Test with string "redis"
        with pytest.raises(
            CallGateRedisConfigurationError,
            match="Redis storage requires a pre-initialized",
        ):
            CallGate(
                random_name(),
                timedelta(seconds=1),
                timedelta(milliseconds=100),
                storage="redis",
            )


if __name__ == "__main__":
    pytest.main()
