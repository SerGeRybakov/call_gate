import faulthandler
import os

from datetime import timedelta

import pytest


try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from call_gate import CallGate
from tests.cluster.utils import ClusterManager
from tests.parameters import random_name, storages


def _cleanup_redis_db():
    """Clean Redis database thoroughly."""
    if not REDIS_AVAILABLE:
        return

    try:
        r = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)

        # Use FLUSHDB to completely clear the database - much faster than keys + delete
        r.flushdb()

        # Also ensure any remaining connections are closed
        r.connection_pool.disconnect()

    except (redis.ConnectionError, redis.TimeoutError, redis.ResponseError):
        # Redis not available or error occurred, skip cleanup
        pass


def _cleanup_redis_cluster():
    """Clean Redis cluster thoroughly."""
    # Skip cluster cleanup in GitHub Actions - no cluster available
    if os.getenv("GITHUB_ACTIONS") == "true":
        return

    try:
        manager = ClusterManager()
        cluster_client = manager.get_cluster_client()
        # Use FLUSHALL to clear all databases on all nodes
        cluster_client.flushall()
        # Close connections
        cluster_client.connection_pool.disconnect()
    except Exception:
        # Cluster not available or error occurred, skip cleanup
        pass


def _cleanup_all_redis():
    """Clean both regular Redis and Redis cluster."""
    _cleanup_redis_db()
    _cleanup_redis_cluster()


def pytest_sessionstart(session):
    """Enable faulthandler and make a stack dump if tests are stuck."""
    faulthandler.enable()
    faulthandler.dump_traceback_later(60)

    # Clean all Redis instances at the start of test session
    _cleanup_all_redis()


def pytest_sessionfinish(session, exitstatus):
    """Clean up after all tests are done."""
    # Clean all Redis instances at the end of test session
    _cleanup_all_redis()


@pytest.fixture(scope="function", autouse=True)
def cleanup_redis():
    """Clean up Redis keys before and after each test to ensure isolation."""
    # Clean up before test
    _cleanup_all_redis()

    yield

    # Clean up after test
    _cleanup_all_redis()


@pytest.fixture(scope="session")
def clean_redis_session():
    """Clean all Redis instances once per test session."""
    _cleanup_all_redis()
    yield
    _cleanup_all_redis()


@pytest.fixture(scope="function", params=storages)
def call_gate_2s_1s_no_limits(request):
    gate_name = random_name()
    gate = CallGate(
        name=gate_name, gate_size=timedelta(seconds=2), frame_step=timedelta(seconds=1), storage=request.param
    )
    try:
        yield gate
    finally:
        gate.clear()
        # For Redis storage, ensure complete cleanup
        if request.param in ("redis", "GateStorageType.redis") and REDIS_AVAILABLE:
            try:
                r = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
                # Delete any remaining keys for this gate
                keys_to_delete = []
                for key in r.scan_iter(match=f"*{gate_name}*"):
                    keys_to_delete.append(key)
                if keys_to_delete:
                    r.delete(*keys_to_delete)
            except (redis.ConnectionError, redis.TimeoutError, redis.ResponseError):
                pass


# Cluster fixtures
@pytest.fixture(scope="function")
def cluster_manager():
    """Provide a cluster manager for tests."""
    manager = ClusterManager()

    try:
        # Ensure all nodes are running at start
        manager.start_all_nodes()

        # Wait for cluster to be ready
        if not manager.wait_for_cluster_ready(timeout=30):
            pytest.skip("Redis cluster not available for testing")

        yield manager

    finally:
        # GUARANTEED cleanup: ensure all nodes are running after test
        try:
            print("🔧 Restoring all cluster nodes after test...")
            manager.start_all_nodes()

            # Wait for cluster to stabilize before next test
            if not manager.wait_for_cluster_ready(timeout=30):
                print("⚠️  Warning: Cluster not ready after cleanup")
            else:
                print("✅ Cluster restored successfully")
        except Exception as e:
            print(f"❌ Failed to restore cluster: {e}")
            # Try one more time
            try:
                manager.start_all_nodes()
                manager.wait_for_cluster_ready(timeout=15)
            except Exception:
                pass  # Final fallback


@pytest.fixture(scope="function", params=storages)
def call_gate_2s_1s_gl5(request):
    gate_name = random_name()
    gate = CallGate(
        name=gate_name,
        gate_size=timedelta(seconds=2),
        frame_step=timedelta(seconds=1),
        gate_limit=5,
        storage=request.param,
    )
    try:
        yield gate
    finally:
        gate.clear()
        # For Redis storage, ensure complete cleanup
        if request.param in ("redis", "GateStorageType.redis") and REDIS_AVAILABLE:
            try:
                r = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
                # Delete any remaining keys for this gate
                keys_to_delete = []
                for key in r.scan_iter(match=f"*{gate_name}*"):
                    keys_to_delete.append(key)
                if keys_to_delete:
                    r.delete(*keys_to_delete)
            except (redis.ConnectionError, redis.TimeoutError, redis.ResponseError):
                pass


@pytest.fixture(scope="function", params=storages)
def call_gate_2s_1s_fl5(request):
    gate_name = random_name()
    gate = CallGate(
        name=gate_name,
        gate_size=timedelta(seconds=2),
        frame_step=timedelta(seconds=1),
        frame_limit=5,
        storage=request.param,
    )
    try:
        yield gate
    finally:
        gate.clear()
        # For Redis storage, ensure complete cleanup
        if request.param in ("redis", "GateStorageType.redis") and REDIS_AVAILABLE:
            try:
                r = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
                # Delete any remaining keys for this gate
                keys_to_delete = []
                for key in r.scan_iter(match=f"*{gate_name}*"):
                    keys_to_delete.append(key)
                if keys_to_delete:
                    r.delete(*keys_to_delete)
            except (redis.ConnectionError, redis.TimeoutError, redis.ResponseError):
                pass
