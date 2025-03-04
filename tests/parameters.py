import uuid

from faker import Faker

from call_gate import GateStorageType


storages = ["simple", "shared", "redis", GateStorageType.simple, GateStorageType.shared, GateStorageType.redis]

start_methods = ["fork", "spawn", "forkserver"]


def random_name() -> str:
    return f"{uuid.uuid4()}_{Faker().name()}"
