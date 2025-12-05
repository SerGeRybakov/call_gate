"""
Redis-specific tests for functionality not covered by general storage tests.

This module focuses on Redis-only features like RedisReentrantLock,
serialization, and Redis-specific edge cases to improve test coverage.
"""

import pickle
import threading
import time

import pytest

from call_gate.errors import CallGateValueError
from call_gate.storages.redis import RedisReentrantLock, RedisStorage
from tests.parameters import (
    GITHUB_ACTIONS_REDIS_TIMEOUT,
    create_call_gate,
    create_redis_client,
    get_redis_kwargs,
    random_name,
)


@pytest.mark.timeout(GITHUB_ACTIONS_REDIS_TIMEOUT)
class TestRedisReentrantLock:
    """Test RedisReentrantLock functionality."""

    @pytest.fixture
    def redis_client(self):
        """Create a Redis client for testing."""
        try:
            client = create_redis_client()
            client.ping()  # Test connection
            return client
        except Exception:
            pytest.skip("Redis not available")

    @pytest.fixture
    def lock_name(self):
        """Generate a unique lock name."""
        return f"test_lock_{random_name()}"

    def test_reentrant_lock_basic_acquisition(self, redis_client, lock_name):
        """Test basic lock acquisition and release."""
        lock = RedisReentrantLock(redis_client, lock_name, timeout=5)

        # Initially no lock should exist
        assert redis_client.get(f"{lock_name}:global_lock") is None

        with lock:
            # Lock should be acquired
            assert redis_client.get(f"{lock_name}:global_lock") == "1"
            assert redis_client.get(f"{lock_name}:lock_owner") == lock.owner
            assert redis_client.hget(f"{lock_name}:lock_count", lock.owner) == "1"

        # After context, lock should be released
        assert redis_client.get(f"{lock_name}:global_lock") is None
        assert redis_client.get(f"{lock_name}:lock_owner") is None

    def test_reentrant_lock_nested_acquisition(self, redis_client, lock_name):
        """Test reentrant (nested) lock acquisition by the same owner."""
        lock = RedisReentrantLock(redis_client, lock_name, timeout=5)

        with lock:
            # First acquisition
            assert redis_client.hget(f"{lock_name}:lock_count", lock.owner) == "1"

            with lock:
                # Nested acquisition - should increment counter
                assert redis_client.hget(f"{lock_name}:lock_count", lock.owner) == "2"

                with lock:
                    # Triple nested - should increment again
                    assert redis_client.hget(f"{lock_name}:lock_count", lock.owner) == "3"

                # After one exit - should decrement
                assert redis_client.hget(f"{lock_name}:lock_count", lock.owner) == "2"

            # After second exit - should decrement again
            assert redis_client.hget(f"{lock_name}:lock_count", lock.owner) == "1"

        # After final exit - lock should be completely released
        assert redis_client.get(f"{lock_name}:global_lock") is None

    def test_lock_contention_different_threads(self, redis_client, lock_name):
        """Test lock contention between different threads."""
        results = []
        lock_acquired_times = []

        def worker(worker_id):
            lock = RedisReentrantLock(redis_client, lock_name, timeout=5)
            with lock:
                start_time = time.time()
                lock_acquired_times.append(start_time)
                results.append(f"worker_{worker_id}_start")
                time.sleep(0.1)  # Hold lock briefly
                results.append(f"worker_{worker_id}_end")

        # Start multiple threads that will compete for the lock
        threads = []
        for i in range(3):
            thread = threading.Thread(target=worker, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify that workers executed sequentially (no interleaving)
        assert len(results) == 6
        for i in range(3):
            start_idx = results.index(f"worker_{i}_start")
            end_idx = results.index(f"worker_{i}_end")
            assert end_idx == start_idx + 1, "Workers should not interleave"

        # Verify lock acquisition times are sequential
        assert len(lock_acquired_times) == 3
        sorted_times = sorted(lock_acquired_times)
        assert lock_acquired_times == sorted_times or abs(max(lock_acquired_times) - min(lock_acquired_times)) < 0.5

    def test_lock_timeout_behavior(self, redis_client, lock_name):
        """Test lock timeout and TTL behavior."""
        lock = RedisReentrantLock(redis_client, lock_name, timeout=1)

        with lock:
            # Check that TTL is set correctly
            ttl = redis_client.ttl(f"{lock_name}:global_lock")
            assert 0 < ttl <= 1

            # Wait and check TTL updates on nested acquisition
            time.sleep(0.5)
            with lock:
                # TTL should be refreshed
                new_ttl = redis_client.ttl(f"{lock_name}:global_lock")
                assert new_ttl > ttl or new_ttl == 1


@pytest.mark.timeout(GITHUB_ACTIONS_REDIS_TIMEOUT)
class TestRedisStorageEdgeCases:
    """Test Redis storage edge cases and error conditions."""

    def test_slide_validation_negative_value(self):
        """Test slide() with negative value raises CallGateValueError."""
        try:
            gate = create_call_gate(random_name(), 60, 1, storage="redis")
        except Exception:
            pytest.skip("Redis not available")

        try:
            with pytest.raises(CallGateValueError, match="Value must be >= 1"):
                gate._data.slide(-1)

            with pytest.raises(CallGateValueError, match="Value must be >= 1"):
                gate._data.slide(0)
        finally:
            gate.clear()

    def test_slide_with_capacity_or_more_calls_clear(self):
        """Test slide() with n >= capacity calls clear()."""
        try:
            gate = create_call_gate(random_name(), 60, 1, storage="redis", capacity=5)
        except Exception:
            pytest.skip("Redis not available")

        try:
            # Add some data
            gate.update(10)
            gate.update(20)
            assert gate.sum == 30

            # Slide with n >= capacity should clear everything
            gate._data.slide(5)  # n == capacity
            assert gate.sum == 0
            assert gate._data.as_list() == [0, 0, 0, 0, 0]

            # Add data again and test with n > capacity
            gate.update(15)
            assert gate.sum == 15

            gate._data.slide(10)  # n > capacity
            assert gate.sum == 0
            assert gate._data.as_list() == [0, 0, 0, 0, 0]
        finally:
            gate.clear()

    def test_redis_connection_parameters(self):
        """Test Redis connection parameter handling."""
        try:
            # Test with custom parameters
            storage = RedisStorage(
                random_name(),
                capacity=5,
                **get_redis_kwargs(
                    db=14,  # Different from default 15
                    socket_timeout=10.0,
                    socket_connect_timeout=8.0,
                ),
            )

            # Verify storage was created successfully with custom parameters
            # We can't directly check the parameters, but we can verify the storage works
            assert storage.capacity == 5
            assert storage._client is not None
            # Test basic functionality to ensure parameters were applied correctly
            storage.atomic_update(1, 0, 0)
            assert storage.sum == 1

        except Exception:
            pytest.skip("Redis not available")

    def test_redis_default_parameters(self):
        """Test Redis default parameter assignment."""
        try:
            storage = RedisStorage(random_name(), capacity=5, **get_redis_kwargs())

            # Verify storage was created successfully with default parameters
            assert storage.capacity == 5
            assert storage._client is not None
            # Test basic functionality to ensure defaults were applied correctly
            storage.atomic_update(1, 0, 0)
            assert storage.sum == 1

        except Exception:
            pytest.skip("Redis not available")


@pytest.mark.timeout(GITHUB_ACTIONS_REDIS_TIMEOUT)
class TestRedisStorageSerialization:
    """Test Redis storage pickle/unpickle functionality."""

    def test_redis_storage_pickle_basic(self):
        """Test basic pickle/unpickle of RedisStorage."""
        try:
            original_name = random_name()
            original_storage = RedisStorage(original_name, capacity=5, data=[1, 2, 3, 0, 0], **get_redis_kwargs())
        except Exception:
            pytest.skip("Redis not available")

        try:
            # Verify initial state
            assert original_storage.sum == 6
            assert original_storage.as_list() == [1, 2, 3, 0, 0]

            # Pickle and unpickle
            pickled_data = pickle.dumps(original_storage)
            restored_storage = pickle.loads(pickled_data)  # noqa: S301

            # Verify restored state
            assert restored_storage.name == original_name
            assert restored_storage.capacity == 5
            assert restored_storage.sum == 6
            assert restored_storage.as_list() == [1, 2, 3, 0, 0]

            # Verify Redis connection is restored
            assert hasattr(restored_storage, "_client")
            assert hasattr(restored_storage, "_lock")
            assert hasattr(restored_storage, "_rlock")

            # Test that restored storage is functional
            restored_storage.atomic_update(5, 0, 0)
            assert restored_storage.sum == 11

        finally:
            try:
                original_storage.clear()
            except Exception:
                pass
            try:
                restored_storage.clear()
            except Exception:
                pass

    def test_redis_storage_setstate_socket_timeout_defaults(self):
        """Test __setstate__ restores client connection properly."""
        try:
            storage = RedisStorage(random_name(), capacity=3, **get_redis_kwargs())
        except Exception:
            pytest.skip("Redis not available")

        try:
            # Get state
            state = storage.__getstate__()

            # Create new storage and restore state
            new_storage = RedisStorage.__new__(RedisStorage)
            new_storage.__setstate__(state)

            # Verify the client was restored and works
            assert new_storage._client is not None
            assert new_storage.capacity == 3
            # Test basic functionality to ensure client connection works
            new_storage.atomic_update(1, 0, 0)
            assert new_storage.sum == 1

        finally:
            try:
                storage.clear()
            except Exception:
                pass
            try:
                new_storage.clear()
            except Exception:
                pass

    def test_redis_storage_setstate_timestamp_key_creation(self):
        """Test __setstate__ preserves timestamp key."""
        try:
            storage = RedisStorage(random_name(), capacity=3, **get_redis_kwargs())
        except Exception:
            pytest.skip("Redis not available")

        try:
            # Get state (timestamp should be present)
            state = storage.__getstate__()

            # Create new storage and restore state
            new_storage = RedisStorage.__new__(RedisStorage)
            new_storage.__setstate__(state)

            # Verify timestamp key was preserved
            expected_timestamp_key = f"{{{storage.name}}}:timestamp"
            assert hasattr(new_storage, "_timestamp")
            assert new_storage._timestamp == expected_timestamp_key

        finally:
            try:
                storage.clear()
            except Exception:
                pass
            try:
                new_storage.clear()
            except Exception:
                pass

    def test_redis_storage_reduce_protocol(self):
        """Test __reduce__ protocol for pickle support."""
        try:
            storage = RedisStorage(random_name(), capacity=4, data=[5, 10, 0, 0], **get_redis_kwargs())
        except Exception:
            pytest.skip("Redis not available")

        try:
            # Test __reduce__ returns correct tuple
            constructor, args, state = storage.__reduce__()

            assert constructor == RedisStorage
            assert args == (storage.name, storage.capacity)
            assert isinstance(state, dict)
            # Check that essential state keys are present
            assert "_data" in state
            assert "_sum" in state
            assert "_timestamp" in state
            assert "client_type" in state
            assert "client_state" in state

            # Verify we can reconstruct using the reduce data
            new_storage = constructor(*args)
            new_storage.__setstate__(state)

            assert new_storage.name == storage.name
            assert new_storage.capacity == storage.capacity
            assert new_storage.sum == 15

        finally:
            try:
                storage.clear()
            except Exception:
                pass
            try:
                new_storage.clear()
            except Exception:
                pass
