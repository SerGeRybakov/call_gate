"""Test edge cases for CallGate configuration to improve coverage."""

import builtins

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from redis import Redis


try:
    from redis import RedisCluster
except ImportError:
    RedisCluster = None  # type: ignore[misc, assignment]

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

    def test_redis_client_without_decode_responses_raises_error(self):
        """Redis client must be created with decode_responses=True."""
        redis_kwargs = get_redis_kwargs()
        redis_kwargs["decode_responses"] = False
        redis_client = Redis(**redis_kwargs)
        redis_client.ping()

        with pytest.raises(
            CallGateRedisConfigurationError,
            match="decode_responses=True",
        ):
            CallGate(
                random_name(),
                timedelta(seconds=1),
                timedelta(milliseconds=100),
                storage=GateStorageType.redis,
                redis_client=redis_client,
            )

    def test_redis_standalone_client_without_pool_fails_decode_check(self):
        """Standalone Redis client without connection pool cannot prove decode_responses."""
        mock_client = MagicMock(spec=Redis)
        mock_client.connection_pool = None
        mock_client.ping.return_value = True

        assert CallGate._redis_client_has_decode_responses(mock_client) is False

        with pytest.raises(
            CallGateRedisConfigurationError,
            match="decode_responses=True",
        ):
            CallGate(
                random_name(),
                timedelta(seconds=1),
                timedelta(milliseconds=100),
                storage=GateStorageType.redis,
                redis_client=mock_client,
            )

    @pytest.mark.skipif(RedisCluster is None, reason="redis cluster not available")
    def test_redis_cluster_client_without_decode_responses_fails(self):
        """RedisCluster without decode_responses on any node pool is rejected."""
        mock_cluster = MagicMock()
        mock_cluster.ping.return_value = True
        mock_node = MagicMock()
        mock_node.redis_connection.connection_pool.connection_kwargs = {"decode_responses": False}
        mock_cluster.nodes_manager.nodes_cache = {"node": mock_node}

        def isinstance_side_effect(obj, cls):
            if obj is mock_cluster:
                if cls is RedisCluster:
                    return True
                if isinstance(cls, tuple):
                    return any(c is RedisCluster for c in cls)
                if cls is Redis:
                    return False
            return builtins.isinstance(obj, cls)

        with patch("call_gate.gate.isinstance", side_effect=isinstance_side_effect):
            assert CallGate._redis_client_has_decode_responses(mock_cluster) is False

            with pytest.raises(
                CallGateRedisConfigurationError,
                match="decode_responses=True",
            ):
                CallGate(
                    random_name(),
                    timedelta(seconds=1),
                    timedelta(milliseconds=100),
                    storage=GateStorageType.redis,
                    redis_client=mock_cluster,
                )


if __name__ == "__main__":
    pytest.main()
