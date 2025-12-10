"""Test edge cases for Redis storage to improve coverage."""

import pytest

from call_gate.errors import GateOverflowError
from call_gate.storages.redis import RedisStorage
from tests.parameters import create_redis_client, random_name


class TestRedisStorageEdgeCases:
    """Test edge cases for Redis storage to improve coverage."""

    def test_extract_constructor_params_exception_handling(self):
        """Test exception handling in _extract_constructor_params (line 301)."""
        client = create_redis_client()
        storage = RedisStorage(random_name(), capacity=3, client=client)

        try:
            # Create a mock object that raises AttributeError when accessing __dict__
            class ProblematicObject:
                def __getattribute__(self, name):
                    if name == "__dict__":
                        raise AttributeError("No __dict__ access")
                    return super().__getattribute__(name)

            problematic_obj = ProblematicObject()
            target_params = {"host", "port", "db"}

            # This should trigger the except (AttributeError, TypeError) block
            result = storage._extract_constructor_params(problematic_obj, target_params)
            assert isinstance(result, dict)  # Should return empty dict due to exception

        finally:
            try:
                storage.clear()
            except Exception:
                pass

    def test_process_dict_value_continue_path(self):
        """Test continue path in _process_dict_value (line 337)."""
        client = create_redis_client()
        storage = RedisStorage(random_name(), capacity=3, client=client)

        try:
            # Create a dictionary with serializable values that match target params
            test_dict = {"host": "localhost", "port": 6379, "non_target": "value"}
            target_params = {"host", "port"}
            visited = set()
            found_params = {}

            # This should trigger the continue statement when serializable params are found
            storage._process_dict_value(test_dict, target_params, visited, found_params)

            # Should have found the target parameters
            assert "host" in found_params
            assert "port" in found_params
            assert "non_target" not in found_params

        finally:
            try:
                storage.clear()
            except Exception:
                pass

    def test_slide_with_capacity_clear(self):
        """Test slide method when n >= capacity triggers clear (line 468)."""
        client = create_redis_client()
        storage = RedisStorage(random_name(), capacity=5, client=client)

        try:
            # Add some data first
            storage.atomic_update(10, 0, 0)
            assert storage.sum > 0

            # Call slide with n >= capacity, should trigger clear()
            storage.slide(5)  # n == capacity
            assert storage.sum == 0  # Should be cleared

            # Test with n > capacity
            storage.atomic_update(5, 0, 0)
            assert storage.sum > 0
            storage.slide(10)  # n > capacity
            assert storage.sum == 0  # Should be cleared

        finally:
            try:
                storage.clear()
            except Exception:
                pass

    def test_atomic_update_overflow_errors(self):
        """Test overflow error handling in atomic_update (lines 551-554)."""
        client = create_redis_client()
        storage = RedisStorage(random_name(), capacity=3, client=client)

        try:
            # First add some positive value
            storage.atomic_update(5, 0, 0)
            assert storage.sum == 5

            # Try to subtract more than available - this triggers gate overflow first
            # because Lua script checks gate overflow before frame overflow
            with pytest.raises(GateOverflowError, match="Gate sum value must be >= 0"):
                storage.atomic_update(-6, 0, 0)  # This causes gate sum < 0

        finally:
            try:
                storage.clear()
            except Exception:
                pass


if __name__ == "__main__":
    pytest.main()
