"""
Tests for timestamp persistence across all storage types.

This module tests the critical functionality of timestamp persistence
that prevents data loss when services restart with the same gate name.
"""

import time

from datetime import datetime, timedelta

import pytest

from call_gate import CallGate, GateStorageType
from tests.parameters import GITHUB_ACTIONS_REDIS_TIMEOUT, random_name, storages


@pytest.mark.timeout(GITHUB_ACTIONS_REDIS_TIMEOUT)
class TestTimestampPersistence:
    """Test timestamp persistence functionality across all storage types."""

    @pytest.mark.parametrize("storage", storages)
    def test_timestamp_set_and_get(self, storage):
        """Test basic timestamp set and get operations."""
        gate = CallGate(random_name(), 60, 1, storage=storage)
        try:
            # Initially no timestamp
            assert gate._data.get_timestamp() is None

            # Set a timestamp
            test_time = datetime.now()
            gate._data.set_timestamp(test_time)

            # Get timestamp back
            retrieved_time = gate._data.get_timestamp()
            assert retrieved_time is not None

            # Should be very close (within 1 second for precision)
            time_diff = abs((retrieved_time - test_time).total_seconds())
            assert time_diff < 1.0

        finally:
            gate.clear()

    @pytest.mark.parametrize("storage", storages)
    def test_timestamp_clear(self, storage):
        """Test timestamp clearing functionality."""
        gate = CallGate(random_name(), 60, 1, storage=storage)
        try:
            # Set a timestamp
            test_time = datetime.now()
            gate._data.set_timestamp(test_time)
            assert gate._data.get_timestamp() is not None

            # Clear timestamp
            gate._data.clear_timestamp()
            assert gate._data.get_timestamp() is None

        finally:
            gate.clear()

    @pytest.mark.parametrize("storage", storages)
    def test_timestamp_updated_on_update(self, storage):
        """Test that timestamp is updated when gate is updated."""
        gate = CallGate(random_name(), 60, 1, storage=storage)
        try:
            # Initially no timestamp
            assert gate._data.get_timestamp() is None

            # Update the gate
            gate.update(5)

            # Should have timestamp now
            timestamp = gate._data.get_timestamp()
            assert timestamp is not None

            # Should be recent (within last few seconds)
            time_diff = abs((datetime.now() - timestamp).total_seconds())
            assert time_diff < 5.0

        finally:
            gate.clear()

    @pytest.mark.parametrize("storage", storages)
    def test_timestamp_cleared_on_clear(self, storage):
        """Test that timestamp is cleared when gate is cleared."""
        gate = CallGate(random_name(), 60, 1, storage=storage)
        try:
            # Update to set timestamp
            gate.update(5)
            assert gate._data.get_timestamp() is not None

            # Clear the gate
            gate.clear()

            # Timestamp should be cleared
            assert gate._data.get_timestamp() is None

        finally:
            gate.clear()

    @pytest.mark.parametrize("storage", storages)
    def test_timestamp_restoration_on_init(self, storage):
        """Test that timestamp is restored from storage on initialization."""
        gate_name = random_name()

        # Create first gate and update it
        gate1 = CallGate(gate_name, 60, 1, storage=storage)
        try:
            gate1.update(10)
            stored_timestamp = gate1._data.get_timestamp()
            assert stored_timestamp is not None

            # Create second gate with same name
            gate2 = CallGate(gate_name, 60, 1, storage=storage)
            try:
                # Should restore timestamp from storage
                restored_timestamp = gate2._current_dt

                if storage in ("simple", GateStorageType.simple, "shared", GateStorageType.shared):
                    # Simple and Shared storage don't persist between separate instances
                    # (Shared only works between processes from same parent)
                    assert restored_timestamp is None
                else:
                    # Only Redis should restore timestamp between separate instances
                    assert restored_timestamp is not None
                    time_diff = abs((restored_timestamp - stored_timestamp).total_seconds())
                    assert time_diff < 1.0

            finally:
                gate2.clear()
        finally:
            gate1.clear()

    @pytest.mark.parametrize("storage", storages)
    def test_no_slide_on_init_with_stored_timestamp(self, storage):
        """Test that gate doesn't slide on init when timestamp is restored from storage."""
        gate_name = random_name()

        # Create first gate and add some data
        gate1 = CallGate(gate_name, timedelta(minutes=10), timedelta(seconds=1), storage=storage)
        try:
            # Add data to multiple frames
            for i in range(5):
                gate1.update(i + 1)
                time.sleep(0.01)  # Small delay to ensure different frames

            initial_sum = gate1.sum
            initial_data = gate1.data.copy()
            assert initial_sum > 0

            # Create second gate with same name after a short delay
            time.sleep(0.1)  # 100ms delay
            gate2 = CallGate(gate_name, timedelta(minutes=10), timedelta(seconds=1), storage=storage)
            try:
                if storage in ("simple", GateStorageType.simple, "shared", GateStorageType.shared):
                    # Simple and Shared storage start fresh with separate instances
                    # (Shared only works between processes from same parent)
                    assert gate2.sum == 0
                else:
                    # Only Redis should preserve data without sliding
                    # (since 100ms is much less than 10 minute window)
                    assert gate2.sum == initial_sum
                    assert gate2.data == initial_data

            finally:
                gate2.clear()
        finally:
            gate1.clear()

    def test_redis_timestamp_key_format(self):
        """Test that Redis storage uses correct timestamp key format."""
        try:
            # Try to create a Redis gate to test if Redis is available
            gate_name = random_name()
            gate = CallGate(gate_name, 60, 1, storage="redis")
        except Exception:
            pytest.skip("Redis not available")

        try:
            # Check that timestamp key is correctly formatted
            expected_key = f"{gate_name}:timestamp"
            assert gate._data._timestamp == expected_key

            # Update gate to set timestamp
            gate.update(1)

            # Check that key exists in Redis
            assert gate._data._client.exists(expected_key)

        finally:
            gate.clear()

    @pytest.mark.parametrize(
        "storage",
        [s for s in storages if s not in ("simple", GateStorageType.simple, "shared", GateStorageType.shared)],
    )
    def test_service_restart_scenario(self, storage):
        """Test the main scenario: service restart with existing data.

        Note: Only Redis supports true persistence between separate service instances.
        Shared storage only works between processes from the same parent.
        """
        gate_name = random_name()

        # Simulate first service running for a while
        service1 = CallGate(gate_name, timedelta(hours=1), timedelta(minutes=1), storage=storage)
        try:
            # Add data over several minutes (simulated)
            for i in range(10):
                service1.update(i + 1)

            original_sum = service1.sum
            original_data = service1.data.copy()
            assert original_sum > 0

            # Simulate service restart after a few minutes
            # (much less than 1 hour window)
            service2 = CallGate(gate_name, timedelta(hours=1), timedelta(minutes=1), storage=storage)
            try:
                # Data should be preserved (no clearing due to timestamp restoration)
                assert service2.sum == original_sum
                assert service2.data == original_data

                # Should be able to continue updating
                service2.update(100)
                assert service2.sum == original_sum + 100

            finally:
                service2.clear()
        finally:
            service1.clear()
