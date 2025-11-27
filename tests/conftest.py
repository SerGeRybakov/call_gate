import faulthandler

from datetime import timedelta

import pytest


try:
    import redis

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from call_gate import CallGate
from tests.parameters import random_name, storages


def _cleanup_redis_db():
    """Helper function to thoroughly clean Redis database."""
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


def pytest_sessionstart(session):
    """Enable faulthandler and make a stack dump if tests are stuck."""
    faulthandler.enable()
    faulthandler.dump_traceback_later(60)

    # Clean Redis at the start of test session
    _cleanup_redis_db()


def pytest_sessionfinish(session, exitstatus):
    """Clean up after all tests are done."""
    # Clean Redis at the end of test session
    _cleanup_redis_db()


@pytest.fixture(scope="function", autouse=True)
def cleanup_redis():
    """Clean up Redis keys before and after each test to ensure isolation."""
    # Clean up before test
    _cleanup_redis_db()

    yield

    # Clean up after test
    _cleanup_redis_db()


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
