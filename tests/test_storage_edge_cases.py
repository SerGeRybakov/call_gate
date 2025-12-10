"""Test edge cases for storage classes to improve coverage."""

from datetime import timedelta

import pytest

from call_gate import GateStorageType
from call_gate.storages.redis import RedisStorage
from tests.parameters import create_call_gate, create_redis_client, random_name, storages


class TestStorageEdgeCases:
    """Test edge cases for storage classes to improve coverage."""

    @pytest.mark.parametrize("storage", storages)
    def test_storage_slide_equals_capacity_direct_call(self, storage):
        """Test calling slide() directly with n == capacity."""
        gate = create_call_gate(random_name(), timedelta(seconds=5), timedelta(seconds=1), storage=storage)

        try:
            # Add data to gate
            gate.update(10)
            gate.update(20)
            assert gate.sum == 30

            # Call slide directly with n == capacity
            # Works without deadlock thanks to _clear_unlocked()
            gate._data.slide(gate._data.capacity)

            # All data should be cleared
            assert gate.sum == 0
            assert all(v == 0 for v in gate._data.as_list())

        finally:
            gate.clear()

    @pytest.mark.parametrize("storage", storages)
    def test_storage_slide_greater_than_capacity_direct_call(self, storage):
        """Test calling slide() directly with n > capacity."""
        gate = create_call_gate(random_name(), timedelta(seconds=5), timedelta(seconds=1), storage=storage)

        try:
            # Add data to gate
            gate.update(15)
            gate.update(25)
            assert gate.sum == 40

            # Call slide directly with n > capacity
            gate._data.slide(gate._data.capacity + 10)

            # All data should be cleared
            assert gate.sum == 0
            assert all(v == 0 for v in gate._data.as_list())

        finally:
            gate.clear()

    @pytest.mark.parametrize(
        "storage",
        ["simple", "shared", GateStorageType.simple, GateStorageType.shared],
    )
    def test_clear_unlocked_method(self, storage):
        """Test _clear_unlocked() method is called correctly."""
        gate = create_call_gate(random_name(), timedelta(seconds=5), timedelta(seconds=1), storage=storage)

        try:
            # Add some data
            gate.update(10)
            gate.update(20)
            assert gate.sum == 30

            # Clear should work correctly using _clear_unlocked
            gate.clear()

            assert gate.sum == 0
            assert all(v == 0 for v in gate._data.as_list())

        finally:
            gate.clear()

    def test_redis_clear_unlocked_not_implemented(self):
        """Test RedisStorage._clear_unlocked() raises error."""
        client = create_redis_client()
        storage = RedisStorage("test", 5, client=client)

        try:
            # _clear_unlocked should raise NotImplementedError
            with pytest.raises(
                NotImplementedError,
                match="RedisStorage does not support _clear_unlocked",
            ):
                storage._clear_unlocked()
        finally:
            storage.clear()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
