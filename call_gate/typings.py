"""
This module contains type definitions used in the library.

Types are defined to make function signatures more readable and to make it easier
to use type checkers and IDEs.

The types are also used in the documentation to make it easier to understand the
function signatures and the types of the parameters and the return values.
"""

from collections.abc import MutableSequence
from datetime import datetime
from enum import IntEnum, auto
from multiprocessing.shared_memory import ShareableList
from types import TracebackType
from typing import TYPE_CHECKING, Any, NamedTuple, Optional, Protocol, Union

from typing_extensions import Literal


Sentinel = object()

if TYPE_CHECKING:
    try:
        from numpy.typing import NDArray
    except ImportError:
        NDArray = Sentinel


class CallGateLimits(NamedTuple):
    """Representation of gate limits."""

    gate_limit: int
    frame_limit: int


class State(NamedTuple):
    """Representation of a gate storage state.

    Properties:
     - data: list of gate values
     - sum: sum of gate values
    """

    data: list
    sum: int


class GateStorageType(IntEnum):
    """gate storage type.

    - simple: simple in-memory storage (``collections.deque``)
    - shared: ``multiprocessing.ShareableList`` (can not contain integers higher than 2**64-1)
    - redis: Redis storage (needs ``redis`` (``redis-py``) package)
    """

    simple = auto()
    shared = auto()
    redis = auto()


class Frame(NamedTuple):
    """Representation of a gate frame.

    Properties:
     - dt: frame datetime
     - value: frame value
    """

    dt: datetime
    value: int


class LockProtocol(Protocol):  # noqa: D101
    def acquire(self, *args: Any, **kwargs: Any) -> Any: ...  # noqa: D102

    def release(self) -> None: ...  # noqa: D102

    def __enter__(self, *args: Any, **kwargs: Any) -> Any: ...

    def __exit__(
        self,
        exc_type: Optional[type[Exception]],
        exc_val: Optional[Exception],
        exc_tb: Optional[TracebackType],
    ) -> None: ...


class AsyncLockProtocol(Protocol):  # noqa: D101
    async def acquire(self, *args: Any, **kwargs: Any) -> Any: ...  # noqa: D102

    def release(self) -> None: ...  # noqa: D102

    async def __aenter__(self, *args: Any, **kwargs: Any) -> Any: ...

    async def __aexit__(
        self, exc_type: Optional[type[Exception]], exc_val: Optional[Exception], exc_tb: Optional[TracebackType]
    ) -> None: ...


LockType = Union[LockProtocol, AsyncLockProtocol]
StorageType = Union[MutableSequence, ShareableList, "NDArray", str]
GateStorageModeType = Union[GateStorageType, Literal["simple", "shared", "redis"]]


class RedisConfig(NamedTuple):
    """Configuration for single Redis instance connection.

    This class provides type-safe configuration for connecting to a single Redis server.
    All parameters correspond to redis-py Redis class constructor parameters.

    Properties:
     - host: Redis server hostname or IP address
     - port: Redis server port number
     - db: Redis database number to select
     - password: Password for Redis authentication (optional)
     - username: Username for Redis authentication (optional)
     - socket_timeout: Socket timeout in seconds (optional)
     - socket_connect_timeout: Socket connection timeout in seconds (optional)
     - socket_keepalive: Enable TCP keepalive (optional)
     - socket_keepalive_options: TCP keepalive options (optional)
     - connection_pool: Custom connection pool (optional)
     - unix_socket_path: Unix socket path for connection (optional)
     - encoding: String encoding for Redis responses
     - encoding_errors: Error handling for encoding/decoding
     - decode_responses: Automatically decode responses to strings
     - retry_on_timeout: Retry commands on timeout
     - ssl: Enable SSL/TLS connection
     - ssl_keyfile: SSL private key file path (optional)
     - ssl_certfile: SSL certificate file path (optional)
     - ssl_cert_reqs: SSL certificate requirements
     - ssl_ca_certs: SSL CA certificates file path (optional)
     - ssl_check_hostname: Verify SSL hostname
     - max_connections: Maximum connections in pool (optional)
    """

    host: str = "localhost"
    port: int = 6379
    db: int = 15
    password: Optional[str] = None
    username: Optional[str] = None
    socket_timeout: Optional[float] = None
    socket_connect_timeout: Optional[float] = None
    socket_keepalive: Optional[bool] = None
    socket_keepalive_options: Optional[dict[str, Any]] = None
    connection_pool: Optional[Any] = None
    unix_socket_path: Optional[str] = None
    encoding: str = "utf-8"
    encoding_errors: str = "strict"
    decode_responses: bool = True
    retry_on_timeout: bool = False
    ssl: bool = False
    ssl_keyfile: Optional[str] = None
    ssl_certfile: Optional[str] = None
    ssl_cert_reqs: Optional[str] = None
    ssl_ca_certs: Optional[str] = None
    ssl_check_hostname: bool = False
    max_connections: Optional[int] = None


class RedisClusterConfig(NamedTuple):
    """Configuration for Redis cluster connection.

    This class provides type-safe configuration for connecting to a Redis cluster.
    All parameters correspond to redis-py RedisCluster class constructor parameters.

    Properties:
     - startup_nodes: List of cluster nodes as host:port strings or dicts
     - password: Password for Redis authentication (optional)
     - username: Username for Redis authentication (optional)
     - socket_timeout: Socket timeout in seconds (optional)
     - socket_connect_timeout: Socket connection timeout in seconds (optional)
     - socket_keepalive: Enable TCP keepalive (optional)
     - socket_keepalive_options: TCP keepalive options (optional)
     - encoding: String encoding for Redis responses
     - encoding_errors: Error handling for encoding/decoding
     - decode_responses: Automatically decode responses to strings
     - skip_full_coverage_check: Skip cluster coverage validation
     - max_connections_per_node: Maximum connections per cluster node
     - readonly_mode: Enable read-only mode for replica nodes
     - ssl: Enable SSL/TLS connection
     - ssl_keyfile: SSL private key file path (optional)
     - ssl_certfile: SSL certificate file path (optional)
     - ssl_cert_reqs: SSL certificate requirements
     - ssl_ca_certs: SSL CA certificates file path (optional)
     - ssl_check_hostname: Verify SSL hostname
     - cluster_error_retry_attempts: Number of retry attempts for cluster errors
     - retry_on_timeout: Retry commands on timeout
    """

    startup_nodes: list[Union[str, dict[str, Any]]]
    password: Optional[str] = None
    username: Optional[str] = None
    socket_timeout: Optional[float] = None
    socket_connect_timeout: Optional[float] = None
    socket_keepalive: Optional[bool] = None
    socket_keepalive_options: Optional[dict[str, Any]] = None
    encoding: str = "utf-8"
    encoding_errors: str = "strict"
    decode_responses: bool = True
    skip_full_coverage_check: bool = False
    max_connections_per_node: Optional[int] = None
    readonly_mode: bool = False
    ssl: bool = False
    ssl_keyfile: Optional[str] = None
    ssl_certfile: Optional[str] = None
    ssl_cert_reqs: Optional[str] = None
    ssl_ca_certs: Optional[str] = None
    ssl_check_hostname: bool = False
    cluster_error_retry_attempts: int = 3
    retry_on_timeout: bool = False


# Union type for Redis configuration
RedisConfigType = Union[RedisConfig, RedisClusterConfig, dict[str, Any]]
