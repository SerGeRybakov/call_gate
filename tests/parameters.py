import os
import uuid

import pytest

from faker import Faker
from redis import Redis

from call_gate import CallGate, GateStorageType
from tests.cluster.utils import ClusterManager


GITHUB_ACTIONS_REDIS_TIMEOUT = int(os.getenv("GITHUB_ACTIONS_REDIS_TIMEOUT", "60"))

github_actions = os.getenv("GITHUB_ACTIONS") == "true"
xfail_marker = pytest.mark.xfail(reason="Timeout on Redis expected in GitHub Actions") if github_actions else []
# Note: cluster_skip_marker removed - we now support Redis cluster in GitHub Actions via pfapi/redis-cluster-service

storages = [
    "simple",
    "shared",
    pytest.param("redis", marks=xfail_marker),
    "redis_cluster",  # Now supported in GitHub Actions
    GateStorageType.simple,
    GateStorageType.shared,
    pytest.param(GateStorageType.redis, marks=xfail_marker),
]

start_methods = ["fork", "spawn", "forkserver"]


def random_name() -> str:
    return f"{uuid.uuid4()}_{Faker().name()}"


def get_redis_kwargs(db=None, **extra_kwargs):
    """Get Redis connection parameters from environment variables.

    Args:
        db: Redis database number (defaults to 15 for tests)
        **extra_kwargs: Additional Redis parameters to override defaults

    Returns:
        dict: Redis connection parameters
    """
    redis_kwargs = {
        "decode_responses": True,
        "db": db if db is not None else 15,
    }

    # Use environment variables if available (for GitHub Actions)
    if "REDIS_HOST" in os.environ:
        redis_kwargs["host"] = os.environ["REDIS_HOST"]
    if "REDIS_PORT" in os.environ:
        redis_kwargs["port"] = int(os.environ["REDIS_PORT"])
    if "REDIS_DB" in os.environ:
        redis_kwargs["db"] = int(os.environ["REDIS_DB"])

    # Apply any extra parameters (can override defaults)
    redis_kwargs.update(extra_kwargs)

    return redis_kwargs


def create_call_gate(*args, storage=None, **kwargs):
    """Create CallGate with proper Redis configuration if needed.

    Automatically adds Redis connection parameters when storage is Redis or
    Redis cluster.
    """
    if storage in ("redis", GateStorageType.redis):
        # Regular Redis storage
        # Extract Redis-specific kwargs
        redis_db = kwargs.pop("redis_db", None)
        redis_extra = {
            k: v for k, v in kwargs.items() if k in ("host", "port", "socket_timeout", "socket_connect_timeout")
        }

        # Remove Redis params from CallGate kwargs
        for key in redis_extra:
            kwargs.pop(key, None)

        # Add Redis configuration
        redis_kwargs = get_redis_kwargs(db=redis_db, **redis_extra)
        kwargs.update(redis_kwargs)
    elif storage == "redis_cluster":
        # Redis cluster storage - create cluster client
        # Try to get cluster client
        manager = ClusterManager()
        try:
            cluster_client = manager.get_cluster_client()
        except Exception as e:
            # Cluster should be available both locally and in GitHub Actions now
            raise ConnectionError(f"Redis cluster not available: {e}") from e

        # Use GateStorageType.redis with cluster client
        kwargs["redis_client"] = cluster_client
        storage = GateStorageType.redis

    return CallGate(*args, storage=storage, **kwargs)


def create_redis_client(**extra_kwargs):
    """Create Redis client with proper configuration for tests.

    Args:
        **extra_kwargs: Additional Redis parameters

    Returns:
        Redis client instance
    """
    redis_kwargs = get_redis_kwargs(**extra_kwargs)
    return Redis(**redis_kwargs)
