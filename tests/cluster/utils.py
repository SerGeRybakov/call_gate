"""Utilities for managing Redis cluster containers in tests."""

import os
import time

import docker

from redis import RedisCluster
from redis.cluster import ClusterNode


class ClusterManager:
    """Manages Redis cluster containers for testing."""

    def __init__(self):
        """Initialize the cluster manager."""
        self.client = docker.from_env()
        self.node_names = [
            "call-gate-redis-cluster-node-1",
            "call-gate-redis-cluster-node-2",
            "call-gate-redis-cluster-node-3",
        ]
        self.init_container_name = "call-gate-redis-cluster-init"

    def _get_container(self, container_name: str):
        """Get Docker container by name."""
        try:
            return self.client.containers.get(container_name)
        except docker.errors.NotFound:
            return None

    def _get_startup_nodes(self) -> list[ClusterNode]:
        """Get cluster startup nodes based on environment.

        Returns:
            List of ClusterNode objects for cluster initialization.

        Environment detection:
        - GitHub Actions: Uses all 6 nodes (7000-7005) provided by
          redis-cluster-service
        - Docker Compose: Uses 3 nodes (7001-7003) from local setup
        """
        github_actions = os.getenv("GITHUB_ACTIONS") == "true"

        if github_actions:
            # GitHub Actions environment - redis-cluster-service provides 6 nodes
            print("🔧 Detected GitHub Actions - using all 6 cluster nodes")
            return [
                ClusterNode("localhost", 7000),
                ClusterNode("localhost", 7001),
                ClusterNode("localhost", 7002),
                ClusterNode("localhost", 7003),
                ClusterNode("localhost", 7004),
                ClusterNode("localhost", 7005),
            ]
        else:
            # Local Docker Compose environment - 3 nodes available
            print("🔧 Detected local environment - using 3 cluster nodes")
            return [
                ClusterNode("localhost", 7001),
                ClusterNode("localhost", 7002),
                ClusterNode("localhost", 7003),
            ]

    def get_cluster_client(self) -> RedisCluster:
        """Get a Redis cluster client.

        Note: Redis Cluster does not support database selection (db parameter).
        All data is stored in the default logical database.

        Raises:
            ConnectionError: If cluster is not available or connection fails.
        """
        startup_nodes = self._get_startup_nodes()

        # Redis Cluster configuration - no 'db' parameter supported
        client = RedisCluster(
            startup_nodes=startup_nodes,
            decode_responses=True,
            skip_full_coverage_check=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
        )
        try:
            client.ping()
            return client
        except Exception as e:
            raise ConnectionError(f"Redis cluster not available: {e}") from e

    def stop_node(self, node_index: int) -> None:
        """Stop a specific cluster node (0-2)."""
        if not 0 <= node_index <= 2:
            raise ValueError("Node index must be 0, 1, or 2")

        container_name = self.node_names[node_index]
        try:
            container = self.client.containers.get(container_name)
            container.stop()
            print(f"Stopped container: {container_name}")
        except docker.errors.NotFound:
            print(f"Container {container_name} not found")

    def start_node(self, node_index: int) -> None:
        """Start a specific cluster node (0-2)."""
        if not 0 <= node_index <= 2:
            raise ValueError("Node index must be 0, 1, or 2")

        container_name = self.node_names[node_index]
        try:
            container = self.client.containers.get(container_name)
            container.start()
            print(f"Started container: {container_name}")
            # Brief wait for container to initialize
            time.sleep(0.5)
        except docker.errors.NotFound:
            print(f"Container {container_name} not found")

    def stop_all_nodes(self) -> None:
        """Stop all cluster nodes."""
        for i in range(3):
            self.stop_node(i)

    def start_all_nodes(self) -> None:
        """Start all cluster nodes and wait for them to be running."""
        print("🔧 Starting all cluster nodes...")

        for i in range(3):
            self.start_node(i)

        # Wait for all nodes to be actually running
        max_wait = 15
        start_time = time.time()

        while time.time() - start_time < max_wait:
            running_nodes = self.get_running_nodes()
            if len(running_nodes) == 3:
                print("✅ All 3 nodes are running")
                break
            print(f"Waiting for nodes... {len(running_nodes)}/3 running")
            time.sleep(1)
        else:
            print(f"⚠️  Only {len(self.get_running_nodes())}/3 nodes started within {max_wait}s")

        # Additional wait for cluster to stabilize
        time.sleep(2)

    def get_running_nodes(self) -> list[int]:
        """Get list of currently running node indices."""
        running = []
        for i, name in enumerate(self.node_names):
            try:
                container = self.client.containers.get(name)
                if container.status == "running":
                    running.append(i)
            except docker.errors.NotFound:
                pass
        return running

    def wait_for_cluster_ready(self, timeout: int = 30) -> bool:
        """Wait for cluster to be ready and return True if successful."""
        start_time = time.time()
        sleep_interval = 0.5

        while time.time() - start_time < timeout:
            try:
                # First check that all nodes are running
                running_nodes = self.get_running_nodes()
                if len(running_nodes) < 3:
                    print(f"Only {len(running_nodes)}/3 nodes running, waiting...")
                    time.sleep(sleep_interval)
                    sleep_interval = min(sleep_interval * 1.2, 2.0)
                    continue

                # Then try to get a working client
                client = self.get_cluster_client()

                # Test basic operations
                test_key = f"cluster_test_{int(time.time())}"
                client.set(test_key, "test_value")
                value = client.get(test_key)
                client.delete(test_key)

                if value == "test_value":
                    print(f"✅ Cluster ready with {len(running_nodes)} nodes")
                    return True

            except Exception as e:
                print(f"Cluster not ready: {type(e).__name__}")
                pass

            time.sleep(sleep_interval)
            sleep_interval = min(sleep_interval * 1.2, 2.0)

        print(f"❌ Cluster failed to become ready within {timeout}s")
        return False

    def wait_for_node_running(self, node_index: int, timeout: int = 30) -> bool:
        """Wait for a specific node to be running."""
        if not 0 <= node_index <= 2:
            raise ValueError("Node index must be 0, 1, or 2")

        container_name = self.node_names[node_index]
        start_time = time.time()

        while time.time() - start_time < timeout:
            container = self._get_container(container_name)
            if container and container.status == "running":
                return True
            time.sleep(1)
        return False
