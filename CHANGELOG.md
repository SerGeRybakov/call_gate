# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] - 2025-12-09

### ⚠️ BREAKING CHANGES

**This release contains breaking changes that require migration for Redis storage users.**

1. **Redis storage now requires `redis_client` parameter** - removed `**kwargs` support for Redis connection parameters
2. **Redis keys format changed** - v1.x data is incompatible with v2.0.0 (migration required)
3. **`CallGate.from_file()` requires `redis_client` parameter** when restoring Redis storage gates

### Added
- **Redis Cluster Support**: CallGate now supports Redis clusters in addition to single Redis instances
- **Pre-initialized Redis Client Support**: New `redis_client` parameter accepts pre-initialized `Redis` or `RedisCluster` clients
- **Enhanced Type Safety**: Better type annotations and IDE support for Redis configurations
- **New Error Type**: `CallGateRedisConfigurationError` for Redis configuration issues
- [**Code examples**](./examples/)

### Changed
- **Redis Storage Initialization**: `redis_client` parameter is now required (removed `**kwargs`)
- **Redis Keys Format**: Keys now use hash tags for cluster support (`{gate_name}` instead of `gate_name`)
- **Improved Documentation**: All docstrings converted to English with RST format
- **Test Infrastructure**: Added comprehensive cluster tests with fault tolerance scenarios
- **Makefile Enhancements**: Added cluster test targets for all Python versions (3.9-3.14)

### Fixed
- **Connection Validation**: Added ping() validation for Redis clients during CallGate initialization
- **Serialization Handling**: Improved serialization for RedisStorage with pre-initialized clients
- **Docker Compose Configuration**: Fixed cluster configuration with proper network settings
- **Multiprocessing Support**: Fixed pickling issues for all storage types

### Removed
- **`**kwargs` in CallGate.__init__()**: No longer accepts Redis connection parameters (host, port, db, etc.)
- **Legacy Redis Configuration**: Removed automatic Redis client creation from kwargs
- **Old Redis Keys Format**: Keys without hash tags are no longer created

---

## ⚠️ MIGRATION GUIDE v1.x → v2.0.0

### BREAKING CHANGES SUMMARY:
1. Redis storage requires `redis_client` parameter (removed `**kwargs` support)
2. Redis keys format changed - **old v1.x data is incompatible** with v2.0.0
3. `CallGate.from_file()` requires `redis_client` for Redis storage

---

### Data Migration for Redis Storage

**Redis keys format has changed** - old v1.x data will NOT be accessible in v2.0.0.

**Step 1: Export data using v1.x**
```python
# Using CallGate v1.x
from call_gate import CallGate

redis_kwargs = {"host": "localhost", "port": 6379, "db": 15}

gate_v1 = CallGate("my_gate", 60, 1, storage="redis", **redis_kwargs)
gate_v1.to_file("gate_backup.json")
```

**Step 2: Import data using v2.0.0**
```python
# Using CallGate v2.0.0
from call_gate import CallGate
from redis import Redis

redis_kwargs = {"host": "localhost", "port": 6379, "db": 15}

client = Redis(**redis_kwargs, decode_responses=True)
gate_v2 = CallGate.from_file("gate_backup.json", storage="redis", redis_client=client)
# Data is automatically written to Redis with new key format
```

**Why keys changed:**
- v1.x keys: `gate_name`, `gate_name:sum`, `gate_name:timestamp`
- v2.0.0 keys: `{gate_name}`, `{gate_name}:sum`, `{gate_name}:timestamp`
- Hash tags `{...}` ensure all keys for one gate are in the same Redis Cluster slot

### API Changes

**Before (v1.x):**
```python
redis_kwargs = {"host": "localhost", "port": 6379, "db": 15}

gate = CallGate(
    name="my_gate",
    gate_size=60,
    frame_step=1,
    storage="redis",
    **redis_kwargs
)
```

**After (v2.0.0):**
```python
from redis import Redis

redis_kwargs = {"host": "localhost", "port": 6379, "db": 15}

client = Redis(**redis_kwargs, decode_responses=True)
gate = CallGate(
    name="my_gate", 
    gate_size=60,
    frame_step=1,
    storage="redis",
    redis_client=client  # Required parameter
)
```

#### Redis Cluster Usage

```python
from redis import RedisCluster
from redis.cluster import ClusterNode

cluster_client = RedisCluster(
    startup_nodes=[
        ClusterNode("node1", 7001),
        ClusterNode("node2", 7002), 
        ClusterNode("node3", 7003)
    ],
    decode_responses=True,
    skip_full_coverage_check=True
)

gate = CallGate(
    name="cluster_gate",
    gate_size=60,
    frame_step=1,
    storage="redis",
    redis_client=cluster_client
)
```

## [1.0.5] - 2025-11-27

### Added
- **Edge Case Testing**: Added comprehensive edge case tests for CallGate, Redis, and storage components
- **Enhanced Test Coverage**: New test files for better coverage of corner cases and error scenarios

### Fixed
- **Test Infrastructure**: Improved test reliability and coverage reporting
- **CI/CD Pipeline**: Enhanced GitHub Actions workflow for better test execution

### Changed
- **Test Organization**: Better organization of test files with dedicated edge case testing

## [1.0.4] - 2025-03-29

### Fixed
- **Redis Storage**: Fixed locks in Redis storage `__getitem__` method for better thread safety
- Improved Redis storage reliability under concurrent access

## [1.0.3] - 2025-03-14

### Fixed
- **Dependencies**: Updated project dependencies and fixed compatibility issues
- **Build System**: Improved build configuration and dependency management

## [1.0.2] - 2025-03-14

### Fixed
- **CI/CD**: Fixed publishing workflow and build process
- **Dependencies**: Resolved dependency conflicts and updated lock file
- **Version Management**: Improved version control system

## [1.0.1] - 2025-03-13

### Added
- **ASGI/WSGI Support**: Added comprehensive tests for ASGI and WSGI server compatibility
- **Server Testing**: Added tests for Uvicorn, Gunicorn, and Hypercorn servers

### Fixed
- **Dependencies**: Updated development dependencies
- **Testing**: Improved test coverage and reliability

## [1.0.0] - 2025-03-05

### Added
- **Initial Release**: First stable release of CallGate
- **Rate Limiting**: Sliding window time-bound rate limiter implementation
- **Storage Types**: Support for simple, shared memory, and Redis storage
- **Thread Safety**: Thread-safe, process-safe, and coroutine-safe operations
- **Async Support**: Full asyncio support with async/await syntax
- **Context Managers**: Support for both sync and async context managers
- **Decorators**: Function and coroutine decorator support
- **Error Handling**: Comprehensive error handling with custom exceptions
- **Persistence**: Save and restore gate state functionality
- **Timezone Support**: Configurable timezone handling
- **Comprehensive Testing**: Extensive test suite with high coverage
