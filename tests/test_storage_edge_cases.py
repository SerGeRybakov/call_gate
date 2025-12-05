"""Test edge cases for storage classes to improve coverage."""

from unittest.mock import Mock

import pytest

from call_gate.storages.shared import SharedMemoryStorage
from call_gate.storages.simple import SimpleStorage
from tests.parameters import random_name


class TestStorageEdgeCases:
    """Test edge cases for storage classes to improve coverage."""

    def test_shared_storage_slide_with_capacity_clear(self):
        """Test SharedMemoryStorage slide method when n >= capacity triggers clear."""
        # Mock the manager and its components to avoid multiprocessing issues
        mock_manager = Mock()
        mock_lock = Mock()
        mock_rlock = Mock()
        mock_list = Mock()
        mock_value = Mock()

        mock_manager.Lock.return_value = mock_lock
        mock_manager.RLock.return_value = mock_rlock
        mock_manager.list.return_value = mock_list
        mock_manager.Value.return_value = mock_value

        # Configure context manager behavior
        mock_lock.__enter__ = Mock(return_value=mock_lock)
        mock_lock.__exit__ = Mock(return_value=None)
        mock_rlock.__enter__ = Mock(return_value=mock_rlock)
        mock_rlock.__exit__ = Mock(return_value=None)

        # Create storage with mocked manager
        storage = SharedMemoryStorage(random_name(), capacity=3, manager=mock_manager)

        # Mock the clear method to track if it was called
        storage.clear = Mock()

        # Test slide with n >= capacity (should trigger clear on line 116)
        storage.slide(3)  # n == capacity
        storage.clear.assert_called_once()

        # Test slide with n > capacity
        storage.clear.reset_mock()
        storage.slide(5)  # n > capacity
        storage.clear.assert_called_once()

    def test_simple_storage_slide_with_capacity_clear(self):
        """Test SimpleStorage slide method when n >= capacity triggers clear."""
        # SimpleStorage doesn't need manager, but we need to mock it for base class
        mock_manager = Mock()
        mock_lock = Mock()
        mock_lock.__enter__ = Mock(return_value=mock_lock)
        mock_lock.__exit__ = Mock(return_value=None)
        mock_manager.Lock.return_value = mock_lock
        mock_manager.RLock.return_value = mock_lock

        storage = SimpleStorage(random_name(), capacity=5, manager=mock_manager)

        # Mock the clear method to track if it was called
        storage.clear = Mock()

        # Test slide with n >= capacity (should trigger clear on line 113)
        storage.slide(5)  # n == capacity
        storage.clear.assert_called_once()

        # Test slide with n > capacity
        storage.clear.reset_mock()
        storage.slide(10)  # n > capacity
        storage.clear.assert_called_once()


if __name__ == "__main__":
    pytest.main()
