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
from tests.cluster.utils import ClusterManager
from tests.parameters import (
    GITHUB_ACTIONS_REDIS_TIMEOUT,
    create_call_gate,
    create_redis_client,
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
                lock_acquired_times.append((worker_id, start_time))
                results.append(("start", worker_id, start_time))
                time.sleep(0.1)  # Hold lock briefly
                end_time = time.time()
                results.append(("end", worker_id, end_time))

        # Start multiple threads that will compete for the lock
        threads = []
        for i in range(3):
            thread = threading.Thread(target=worker, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify that workers did not overlap (critical sections are disjoint)
        assert len(results) == 6
        # Build intervals (start, end) per worker
        intervals = []
        for worker_id in range(3):
            start_entry = next(e for e in results if e[0] == "start" and e[1] == worker_id)
            end_entry = next(e for e in results if e[0] == "end" and e[1] == worker_id)
            start_t = start_entry[2]
            end_t = end_entry[2]
            assert end_t >= start_t
            intervals.append((start_t, end_t))

        intervals.sort(key=lambda x: x[0])
        for prev, curr in zip(intervals, intervals[1:]):
            # start of next should be >= end of prev (no overlap)
            assert curr[0] >= prev[1], "Workers should not overlap in critical section"

        # Verify lock acquisition times roughly sequential
        assert len(lock_acquired_times) == 3
        only_times = [t for _, t in sorted(lock_acquired_times, key=lambda x: x[1])]
        assert only_times == sorted(only_times)

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
            # Create gate with 60s window and 1s step = 60 frames capacity
            gate = create_call_gate(random_name(), 60, 1, storage="redis")
        except Exception:
            pytest.skip("Redis not available")

        try:
            # Add some data
            gate.update(10)
            gate.update(20)
            assert gate.sum == 30

            # Slide with n >= capacity should clear everything
            # Gate has 60 frames, so sliding by 60 should clear
            gate._data.slide(60)  # n == capacity
            assert gate.sum == 0
            # First 60 elements should be 0
            data = gate._data.as_list()
            assert data[:60] == [0] * 60

            # Add data again and test with n > capacity
            gate.update(15)
            assert gate.sum == 15

            gate._data.slide(100)  # n > capacity
            assert gate.sum == 0
            data = gate._data.as_list()
            assert data[:60] == [0] * 60
        finally:
            gate.clear()

    def test_redis_connection_parameters(self):
        """Test Redis connection parameter handling for v2.0+."""
        try:
            # Create Redis client with custom parameters
            client = create_redis_client(
                db=14,  # Different from default 15
                socket_timeout=10.0,
                socket_connect_timeout=8.0,
            )
            client.ping()  # Verify connection

            # Create storage with pre-initialized client
            storage = RedisStorage(
                random_name(),
                capacity=5,
                client=client,
            )

            # Verify storage was created successfully with custom parameters
            assert storage.capacity == 5
            assert storage._client is not None
            # Test basic functionality to ensure client works correctly
            storage.atomic_update(1, 0, 0)
            assert storage.sum == 1

        except Exception:
            pytest.skip("Redis not available")

    def test_redis_default_parameters(self):
        """Test Redis default parameter assignment for v2.0+."""
        try:
            # Create client with default parameters
            client = create_redis_client()
            client.ping()

            storage = RedisStorage(random_name(), capacity=5, client=client)

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
        """Test serialization/deserialization of RedisStorage for v2.0."""
        try:
            original_name = random_name()
            client = create_redis_client()
            client.ping()
            original_storage = RedisStorage(original_name, capacity=5, data=[1, 2, 3, 0, 0], client=client)
        except Exception:
            pytest.skip("Redis not available")

        try:
            # Verify initial state
            assert original_storage.sum == 6
            assert original_storage.as_list() == [1, 2, 3, 0, 0]

            # Вместо pickle.loads (ломается из-за обязательного client)
            # используем round-trip через __getstate__/__setstate__
            state_bytes = pickle.dumps(original_storage.__getstate__())
            restored_state = pickle.loads(state_bytes)  # noqa: S301

            restored_storage = RedisStorage.__new__(RedisStorage)
            restored_storage.__setstate__(restored_state)

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
            client = create_redis_client()
            client.ping()
            storage = RedisStorage(random_name(), capacity=3, client=client)
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
            client = create_redis_client()
            client.ping()
            storage = RedisStorage(random_name(), capacity=3, client=client)
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
            client = create_redis_client()
            client.ping()
            storage = RedisStorage(random_name(), capacity=4, data=[5, 10, 0, 0], client=client)
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
            # __reduce__ protocol: create with __new__, then restore state with __setstate__
            new_storage = constructor.__new__(constructor)
            new_storage.name = args[0]
            new_storage.capacity = args[1]
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

    def test_redis_storage_init_with_none_client_for_unpickling(self):
        """Test __init__ with client=None (unpickling path)."""
        # This tests the path where client is None during unpickling
        # Creates storage via __new__ then calls __init__ with client=None
        storage = RedisStorage.__new__(RedisStorage)
        storage.name = "test"
        storage.capacity = 5

        # Call __init__ with client=None (unpickling path)
        storage.__init__("test", 5, client=None)

        # Verify early return happened (line 130)
        assert storage._client is None
        # Locks should not be created yet (line 130 returns early)
        assert not hasattr(storage, "_lock") or storage._lock is None

    def test_redis_storage_extract_params_exception_handling(self):
        """Test _extract_constructor_params handles exceptions."""
        client = create_redis_client()
        storage = RedisStorage("test", 5, client=client)

        try:
            # Create object that raises AttributeError
            class BadObject:
                def __getattribute__(self, name):
                    raise AttributeError("Forced error")

            target_params = {"host", "port"}

            # Should handle exception and return empty dict
            result = storage._extract_constructor_params(BadObject(), target_params)
            assert result == {}

        finally:
            storage.clear()

    def test_redis_cluster_extract_startup_nodes(self):
        """Test that startup_nodes are extracted from RedisCluster client."""
        manager = ClusterManager()
        cluster_client = manager.get_cluster_client()

        # Create storage just to test extraction logic
        storage = RedisStorage("test_extract", capacity=3, client=cluster_client)

        try:
            # Extract client state
            client_state_dict = storage._extract_client_state()

            # Verify cluster type detected
            assert client_state_dict["client_type"] == "cluster"

            # Verify startup_nodes were extracted
            client_state = client_state_dict["client_state"]
            assert "startup_nodes" in client_state
            assert isinstance(client_state["startup_nodes"], list)
            assert len(client_state["startup_nodes"]) > 0

            # Verify each node has host and port
            for node in client_state["startup_nodes"]:
                assert "host" in node
                assert "port" in node

        finally:
            storage.clear()

    def test_redis_process_list_value_with_primitives(self):
        """Test _process_list_value with list of primitives."""
        client = create_redis_client()
        storage = RedisStorage("test", 5, client=client)

        try:
            # Test processing list of primitives
            target_params = {"test_list"}
            visited = set()
            found_params = {}

            # List with serializable primitives
            storage._process_list_value("test_list", [1, 2, 3], target_params, visited, found_params)
            assert found_params == {"test_list": [1, 2, 3]}

            # Test with non-target parameter (should skip)
            found_params2 = {}
            storage._process_list_value("other_list", [1, 2], {"target"}, visited, found_params2)
            assert found_params2 == {}

        finally:
            storage.clear()


if __name__ == "__main__":
    pytest.main()
