import os
import uuid

import pytest

from faker import Faker

from call_gate import GateStorageType


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
