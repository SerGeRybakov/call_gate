# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2024-12-04

### Added
- **Redis Cluster Support**: CallGate now supports Redis clusters in addition to single Redis instances
- **Pre-initialized Redis Client Support**: New `redis_client` parameter accepts pre-initialized `Redis` or `RedisCluster` clients
- **Enhanced Type Safety**: Better type annotations and IDE support for Redis configurations
- **New Error Type**: `CallGateRedisConfigurationError` for Redis configuration issues

### Changed
- **Redis Storage Initialization**: Now supports both pre-initialized clients and legacy kwargs
- **Improved Documentation**: All docstrings converted to English with RST format
- **Test Infrastructure**: Cluster tests are isolated and excluded from CI/CD pipeline
- **Makefile Enhancements**: Added cluster test targets for all Python versions (3.9-3.14)

### Deprecated
- **Redis Connection Parameters via kwargs**: Using Redis connection parameters through `**kwargs` is deprecated and will be removed in version 2.0.0
- **Legacy Redis Configuration**: Users should migrate to the `redis_client` parameter with pre-initialized clients

### Fixed
- **Connection Validation**: Added ping() validation for Redis clients during CallGate initialization
- **Serialization Handling**: Improved serialization for RedisStorage with pre-initialized clients
- **Docker Compose Configuration**: Removed volumes and auto-restart for better test isolation

### Security
- **Connection Timeouts**: Added default socket timeouts to prevent hanging Redis operations

### Migration Guide

#### From kwargs to redis_client

**Before (deprecated):**
```python
gate = CallGate(
    name="my_gate",
    gate_size=60,
    storage=GateStorageType.redis,
    host="localhost",
    port=6379,
    db=15
)
```

**After (recommended):**
```python
from redis import Redis

client = Redis(host="localhost", port=6379, db=15, decode_responses=True)
gate = CallGate(
    name="my_gate", 
    gate_size=60,
    storage=GateStorageType.redis,
    redis_client=client
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
    storage=GateStorageType.redis,
    redis_client=cluster_client
)
```

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
