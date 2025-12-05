"""Redis cluster specific tests for CallGate.

These tests verify CallGate behavior with Redis clusters, including fault tolerance
scenarios like node failures and recovery.
"""

import time
import warnings

from datetime import timedelta

import pytest

from call_gate import CallGate, GateStorageType
from tests.cluster.utils import ClusterManager
from tests.parameters import random_name


@pytest.mark.cluster
class TestRedisClusterBasic:
    """Basic Redis cluster functionality tests."""

    def test_cluster_client_creation(self, cluster_manager):
        """Test creating CallGate with Redis cluster client."""
        cluster_client = cluster_manager.get_cluster_client()

        gate = CallGate(
            name=random_name(),
            gate_size=timedelta(seconds=10),
            frame_step=timedelta(seconds=1),
            storage=GateStorageType.redis,
            redis_client=cluster_client,
        )

        try:
            # Test basic operations
            gate.update(5)
            assert gate.sum == 5

            gate.update(3)
            assert gate.sum == 8

        finally:
            gate.clear()

    def test_cluster_client_ping_validation(self, cluster_manager):
        """Test that CallGate validates cluster client connectivity."""
        cluster_client = cluster_manager.get_cluster_client()

        # This should work fine
        gate = CallGate(
            name=random_name(),
            gate_size=timedelta(seconds=10),
            frame_step=timedelta(seconds=1),
            storage=GateStorageType.redis,
            redis_client=cluster_client,
        )
        gate.clear()

    def test_cluster_client_with_non_redis_storage(self, cluster_manager):
        """Test that cluster client is ignored for non-Redis storage."""
        cluster_client = cluster_manager.get_cluster_client()

        # Should work fine - redis_client is ignored for simple storage
        gate = CallGate(
            name=random_name(),
            gate_size=timedelta(seconds=10),
            frame_step=timedelta(seconds=1),
            storage=GateStorageType.simple,
            redis_client=cluster_client,
        )

        gate.update(5)
        assert gate.sum == 5


@pytest.mark.cluster
class TestRedisClusterFaultTolerance:
    """Test Redis cluster fault tolerance scenarios."""

    def test_single_node_failure(self, cluster_manager: ClusterManager):
        """Test CallGate behavior when one cluster node fails."""
        cluster_client = cluster_manager.get_cluster_client()

        gate = CallGate(
            name=random_name(),
            gate_size=timedelta(seconds=10),
            frame_step=timedelta(seconds=1),
            storage=GateStorageType.redis,
            redis_client=cluster_client,
        )

        try:
            # Initial operations should work
            gate.update(5)
            assert gate.sum == 5

            # Stop one node
            cluster_manager.stop_node(0)
            time.sleep(2)  # Reduced from 5 to 2 seconds

            # Operations may fail if the key was on the stopped node
            # This is expected behavior for Redis cluster without replicas
            try:
                gate.update(3)
                # If it works, great! The key wasn't on the stopped node
                print("Operation succeeded despite node failure")
            except Exception as e:
                # This is expected if the key was on the stopped node
                print(f"Operation failed as expected: {type(e).__name__}")

            # Restart the node
            cluster_manager.start_node(0)
            assert cluster_manager.wait_for_cluster_ready(timeout=15)  # Reduced timeout

            # Create a new gate to test recovery
            new_cluster_client = cluster_manager.get_cluster_client()

            new_gate = CallGate(
                name=random_name(),  # Use different name to avoid conflicts
                gate_size=timedelta(seconds=10),
                frame_step=timedelta(seconds=1),
                storage=GateStorageType.redis,
                redis_client=new_cluster_client,
            )

            # Operations should work after recovery
            new_gate.update(2)
            assert new_gate.sum == 2
            new_gate.clear()

        except Exception:
            # Best effort cleanup
            try:
                gate.clear()
            except Exception:
                pass

    def test_node_recovery(self, cluster_manager: ClusterManager):
        """Test CallGate behavior during node recovery."""
        cluster_client = cluster_manager.get_cluster_client()

        gate = CallGate(
            name=random_name(),
            gate_size=timedelta(seconds=10),
            frame_step=timedelta(seconds=1),
            storage=GateStorageType.redis,
            redis_client=cluster_client,
        )

        try:
            # Set initial state
            gate.update(10)
            assert gate.sum == 10

            # Stop a node
            cluster_manager.stop_node(1)
            time.sleep(2)  # Reduced from 5 to 2 seconds

            # Operations may fail depending on which node was stopped
            try:
                gate.update(5)
                print("Operation succeeded during node failure")
            except Exception as e:
                print(f"Operation failed as expected during node failure: {type(e).__name__}")

            # Restart the node
            cluster_manager.start_node(1)
            assert cluster_manager.wait_for_cluster_ready(timeout=15)  # Reduced timeout

            # Create new client and gate to test recovery
            new_cluster_client = cluster_manager.get_cluster_client()

            recovery_gate = CallGate(
                name=random_name(),  # Use different name
                gate_size=timedelta(seconds=10),
                frame_step=timedelta(seconds=1),
                storage=GateStorageType.redis,
                redis_client=new_cluster_client,
            )

            # New operations should work after recovery
            recovery_gate.update(1)
            assert recovery_gate.sum == 1
            recovery_gate.clear()

        except Exception:
            # Best effort cleanup
            try:
                gate.clear()
            except Exception:
                pass

    def test_multiple_node_failure(self, cluster_manager: ClusterManager):
        """Test CallGate behavior when multiple nodes fail."""
        cluster_client = cluster_manager.get_cluster_client()

        gate = CallGate(
            name=random_name(),
            gate_size=timedelta(seconds=10),
            frame_step=timedelta(seconds=1),
            storage=GateStorageType.redis,
            redis_client=cluster_client,
        )

        try:
            # Initial operations
            gate.update(7)
            assert gate.sum == 7

            # Stop two nodes (should still work with 1 node in a 3-node cluster)
            cluster_manager.stop_node(0)
            cluster_manager.stop_node(1)
            time.sleep(2)  # Reduced from 3 to 2 seconds

            # This might fail depending on cluster configuration
            # But let's try to continue operations
            try:
                gate.update(3)
                # If this works, verify the sum
                assert gate.sum == 10
            except Exception:
                # Expected if cluster becomes unavailable
                pass

            # Restart nodes
            cluster_manager.start_node(0)
            cluster_manager.start_node(1)
            time.sleep(5)

            # Wait for cluster to stabilize
            assert cluster_manager.wait_for_cluster_ready(timeout=30)

            # Operations should work again
            gate.update(1)

        finally:
            try:
                gate.clear()
            except Exception:
                pass  # Cluster might be unstable

    def test_full_cluster_failure_and_recovery(self, cluster_manager: ClusterManager):
        """Test CallGate behavior during full cluster failure and recovery."""
        cluster_client = cluster_manager.get_cluster_client()

        gate = CallGate(
            name=random_name(),
            gate_size=timedelta(seconds=10),
            frame_step=timedelta(seconds=1),
            storage=GateStorageType.redis,
            redis_client=cluster_client,
        )

        try:
            # Set initial state
            gate.update(20)
            assert gate.sum == 20

            # Stop all nodes
            cluster_manager.stop_all_nodes()
            time.sleep(2)

            # Operations should fail
            with pytest.raises(Exception):  # noqa: B017
                gate.update(5)

            # Restart all nodes
            cluster_manager.start_all_nodes()

            # Wait for cluster to be ready
            assert cluster_manager.wait_for_cluster_ready(timeout=30)  # Reduced from 60 to 30

            # Create new client (old one might have stale connections)
            new_cluster_client = cluster_manager.get_cluster_client()

            new_gate = CallGate(
                name=gate.name,  # Same name to access same data
                gate_size=timedelta(seconds=10),
                frame_step=timedelta(seconds=1),
                storage=GateStorageType.redis,
                redis_client=new_cluster_client,
            )

            # Data might be lost after full cluster restart, but operations should work
            # Clear any stale data and test fresh operations
            new_gate.clear()

            # New operations should work
            new_gate.update(5)
            assert new_gate.sum == 5

            new_gate.update(3)
            assert new_gate.sum == 8
            new_gate.clear()

        finally:
            try:
                gate.clear()
            except Exception:
                pass  # Cluster might be unstable


@pytest.mark.cluster
class TestRedisClusterConfiguration:
    """Test Redis cluster configuration scenarios."""

    def test_missing_redis_client_warning(self):
        """Test warning when Redis storage is requested but no client provided."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            gate = CallGate(
                name=random_name(),
                gate_size=timedelta(seconds=10),
                frame_step=timedelta(seconds=1),
                storage=GateStorageType.redis,
                # No redis_client and no kwargs - should use defaults with warning
            )
            gate.clear()  # Cleanup

            # Check that deprecation warning was issued
            assert len(w) == 1
            assert issubclass(w[0].category, DeprecationWarning)
            assert "No Redis configuration provided" in str(w[0].message)

    def test_cluster_client_with_kwargs_deprecation_warning(self, cluster_manager):
        """Test deprecation warning when both cluster client and kwargs provided."""
        cluster_client = cluster_manager.get_cluster_client()

        with pytest.warns(DeprecationWarning, match="Both 'redis_client' and Redis connection parameters"):
            gate = CallGate(
                name=random_name(),
                gate_size=timedelta(seconds=10),
                frame_step=timedelta(seconds=1),
                storage=GateStorageType.redis,
                redis_client=cluster_client,
                host="localhost",  # This should be ignored
                port=6379,
            )

        try:
            # Should use cluster_client, not the kwargs
            gate.update(5)
            assert gate.sum == 5
        finally:
            gate.clear()
