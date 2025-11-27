import os
import uuid

import pytest

from faker import Faker

from call_gate import CallGate, GateStorageType


GITHUB_ACTIONS_REDIS_TIMEOUT = int(os.getenv("GITHUB_ACTIONS_REDIS_TIMEOUT", "60"))

github_actions = os.getenv("GITHUB_ACTIONS") == "true"
xfail_marker = pytest.mark.xfail(reason="Timeout on Redis expected in GitHub Actions") if github_actions else []

storages = [
    "simple",
    "shared",
    pytest.param("redis", marks=xfail_marker),
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

    Automatically adds Redis connection parameters when storage is Redis.
    """
    if storage in ("redis", GateStorageType.redis):
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

    return CallGate(*args, storage=storage, **kwargs)


def create_redis_client(**extra_kwargs):
    """Create Redis client with proper configuration for tests.

    Args:
        **extra_kwargs: Additional Redis parameters

    Returns:
        Redis client instance
    """
    from redis import Redis

    redis_kwargs = get_redis_kwargs(**extra_kwargs)
    return Redis(**redis_kwargs)
