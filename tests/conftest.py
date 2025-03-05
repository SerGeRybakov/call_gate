import faulthandler

from datetime import timedelta

import pytest

from call_gate import CallGate
from tests.parameters import random_name, storages


def pytest_sessionstart(session):
    """Enable faulthandler and make a stack dump if tests are stuck."""
    faulthandler.enable()
    faulthandler.dump_traceback_later(60)


@pytest.fixture(scope="function", params=storages)
def call_gate_2s_1s_no_limits(request):
    gate = CallGate(
        name=random_name(), gate_size=timedelta(seconds=2), frame_step=timedelta(seconds=1), storage=request.param
    )
    try:
        yield gate
    finally:
        gate.clear()


@pytest.fixture(scope="function", params=storages)
def call_gate_2s_1s_gl5(request):
    gate = CallGate(
        name=random_name(),
        gate_size=timedelta(seconds=2),
        frame_step=timedelta(seconds=1),
        gate_limit=5,
        storage=request.param,
    )
    try:
        yield gate
    finally:
        gate.clear()


@pytest.fixture(scope="function", params=storages)
def call_gate_2s_1s_fl5(request):
    gate = CallGate(
        name=random_name(),
        gate_size=timedelta(seconds=2),
        frame_step=timedelta(seconds=1),
        frame_limit=5,
        storage=request.param,
    )
    try:
        yield gate
    finally:
        gate.clear()
