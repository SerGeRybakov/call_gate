from datetime import timedelta

import pytest

from call_gate import CallGate


@pytest.fixture(scope="function")
def sliding_gate_2s_1s_no_limits():
    return CallGate(timedelta(seconds=2), timedelta(seconds=1))


@pytest.fixture(scope="function")
def sliding_gate_gate_2s_1s_wl5():
    return CallGate(timedelta(seconds=2), timedelta(seconds=1), gate_limit=5)


@pytest.fixture(scope="function")
def sliding_gate_frame_2s_1s_fl5():
    return CallGate(timedelta(seconds=2), timedelta(seconds=1), frame_limit=5)


def new_win_24h_1m_wl2000():
    """It's not a fixture, but called inside other fixtures."""
    return CallGate(timedelta(hours=24), timedelta(minutes=1), gate_limit=2000)


def new_win_10m_1s_wl1200_fl2():
    """It's not a fixture, but called inside other fixtures."""
    return CallGate(timedelta(minutes=10), timedelta(seconds=1), gate_limit=1200, frame_limit=2)
