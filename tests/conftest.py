import faulthandler
import os
import signal
import sys

from datetime import timedelta

import pytest

from call_gate import GateStorageType
from tests.cluster.utils import ClusterManager
from tests.parameters import (
    create_call_gate,
    create_redis_client,
    create_redis_cluster_client,
    random_name,
    storages,
)


try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


def _cleanup_redis_db():
    """Clean Redis database thoroughly."""
    if not REDIS_AVAILABLE:
        return

    try:
        r = create_redis_client()

        # First, try to delete any stuck locks (prevent deadlocks)
        try:
            for key in r.scan_iter(match="*:lock*"):
                r.delete(key)
        except Exception:
            pass

        # Use FLUSHDB to completely clear the database
        r.flushdb()

        # Force close all connections to prevent stale connections
        try:
            r.connection_pool.disconnect()
        except Exception:
            pass

        # Close the client itself
        try:
            r.close()
        except Exception:
            pass
    except (redis.ConnectionError, redis.TimeoutError, redis.ResponseError):
        # Redis not available or error occurred, skip cleanup
        pass


def _cleanup_redis_cluster():
    """Clean Redis cluster thoroughly."""
    try:
        cluster_client = create_redis_cluster_client()
        # Use FLUSHALL to clear all databases on all nodes
        cluster_client.flushall()

        # Force close all connections
        try:
            cluster_client.connection_pool.disconnect()
        except Exception:
            pass

        # Close the client itself
        try:
            cluster_client.close()
        except Exception:
            pass
    except Exception:
        # Cluster not available or error occurred, skip cleanup
        pass


def _cleanup_all_redis():
    """Clean both regular Redis and Redis cluster."""
    _cleanup_redis_db()
    _cleanup_redis_cluster()


def pytest_configure(config):
    """Configure pytest before test collection."""
    # Enable faulthandler as early as possible
    faulthandler.enable(file=sys.stderr, all_threads=True)


def pytest_sessionstart(session):
    """Enable faulthandler and make a stack dump if tests are stuck."""
    # Re-enable with traceback dump for hanging tests
    faulthandler.dump_traceback_later(60, file=sys.stderr)

    # Register SIGSEGV handler to fail tests explicitly
    def segfault_handler(signum, frame):
        sys.stderr.write("\n" + "=" * 70 + "\n")
        sys.stderr.write("CRITICAL: SIGSEGV (Segmentation Fault) detected!\n")
        sys.stderr.write("=" * 70 + "\n")
        sys.stderr.flush()
        faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
        sys.stderr.flush()
        # Force exit with error code
        os._exit(139)  # Use os._exit to bypass any cleanup that might segfault

    signal.signal(signal.SIGSEGV, segfault_handler)

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
    gate = create_call_gate(
        name=gate_name, gate_size=timedelta(seconds=2), frame_step=timedelta(seconds=1), storage=request.param
    )
    try:
        yield gate
    finally:
        gate.clear()
        # For Redis storage, ensure complete cleanup
        if request.param in ("redis", GateStorageType.redis) and REDIS_AVAILABLE:
            try:
                r = create_redis_client()
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
        # In GitHub Actions, skip container management - cluster is managed by systemctl
        if not manager.github_actions:
            # Ensure all nodes are running at start (local Docker Compose only)
            running = manager.get_running_nodes()
            if len(running) < 3:
                manager.start_all_nodes()

                # Wait for cluster to be ready
                if not manager.wait_for_cluster_ready(timeout=30):
                    raise ConnectionError("Cluster not ready.")
        # In GitHub Actions, just verify cluster is available
        elif not manager.wait_for_cluster_ready(timeout=30):
            raise ConnectionError("Cluster not ready in GitHub Actions.")

        yield manager

    finally:
        # GUARANTEED cleanup: ensure all nodes are running after test (local only)
        if not manager.github_actions:
            try:
                # Wait for cluster to stabilize before next test
                running = manager.get_running_nodes()
                if len(running) < 3:
                    print("🔧 Restoring all cluster nodes after test...")
                    manager.start_all_nodes()

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
    gate = create_call_gate(
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
        if request.param in ("redis", GateStorageType.redis) and REDIS_AVAILABLE:
            try:
                r = create_redis_client()
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
    gate = create_call_gate(
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
        if request.param in ("redis", GateStorageType.redis) and REDIS_AVAILABLE:
            try:
                r = create_redis_client()
                # Delete any remaining keys for this gate
                keys_to_delete = []
                for key in r.scan_iter(match=f"*{gate_name}*"):
                    keys_to_delete.append(key)
                if keys_to_delete:
                    r.delete(*keys_to_delete)
            except (redis.ConnectionError, redis.TimeoutError, redis.ResponseError):
                pass
