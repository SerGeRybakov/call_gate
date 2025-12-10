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


def create_redis_client(**extra_kwargs):
    """Create Redis client with proper configuration for tests.

    Args:
        **extra_kwargs: Additional Redis parameters (e.g., db, host, port)

    Returns:
        Redis: Redis client instance

    Raises:
        ConnectionError: If Redis is not available
    """
    redis_kwargs = get_redis_kwargs(**extra_kwargs)
    client = Redis(**redis_kwargs)
    try:
        client.ping()
        return client
    except Exception as e:
        raise ConnectionError(f"Redis not available: {e}") from e


def create_redis_cluster_client():
    """Create Redis cluster client for tests.

    Returns:
        RedisCluster: Redis cluster client instance

    Raises:
        ConnectionError: If cluster is not available
    """
    manager = ClusterManager()
    try:
        cluster_client = manager.get_cluster_client()
        return cluster_client
    except Exception as e:
        raise ConnectionError(f"Redis cluster not available: {e}") from e


def create_call_gate(*args, storage=None, **kwargs):
    """Create CallGate with proper Redis configuration if needed.

    For v2.0.0+: Automatically creates and passes Redis/RedisCluster client
    when storage is Redis or Redis cluster.

    Args:
        *args: Positional arguments for CallGate
        storage: Storage type (simple, shared, redis, redis_cluster, or GateStorageType enum)
        **kwargs: Keyword arguments for CallGate (redis_db can be passed for Redis storage)

    Returns:
        CallGate: Initialized CallGate instance
    """
    # Remove redis_db if present (used only for creating client)
    redis_db = kwargs.pop("redis_db", None)

    if storage in ("redis", GateStorageType.redis):
        # Regular Redis storage - create and pass client
        redis_client = create_redis_client(db=redis_db)
        kwargs["redis_client"] = redis_client

    elif storage == "redis_cluster":
        # Redis cluster storage - create and pass cluster client
        cluster_client = create_redis_cluster_client()
        kwargs["redis_client"] = cluster_client
        storage = GateStorageType.redis

    return CallGate(*args, storage=storage, **kwargs)


def get_redis_client_if_needed(storage):
    """Get Redis client if storage requires it (for negative tests).

    Args:
        storage: Storage type

    Returns:
        tuple: (redis_client, normalized_storage) where:
            - redis_client: Redis/RedisCluster client or None
            - normalized_storage: Storage value to use (converts redis_cluster to GateStorageType.redis)
    """
    if storage in ("redis", GateStorageType.redis):
        return create_redis_client(), storage
    elif storage in ("redis_cluster",):
        return create_redis_cluster_client(), GateStorageType.redis
    return None, storage
