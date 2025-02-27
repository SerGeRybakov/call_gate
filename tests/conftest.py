from datetime import timedelta

import pytest

from sliding_window import SlidingWindow


@pytest.fixture(scope="function")
def sliding_window_2s_1s_no_limits():
    return SlidingWindow(timedelta(seconds=2), timedelta(seconds=1))


@pytest.fixture(scope="function")
def sliding_window_window_2s_1s_wl5():
    return SlidingWindow(timedelta(seconds=2), timedelta(seconds=1), window_limit=5)


@pytest.fixture(scope="function")
def sliding_window_frame_2s_1s_fl5():
    return SlidingWindow(timedelta(seconds=2), timedelta(seconds=1), frame_limit=5)


def new_win_24h_1m_wl2000():
    """It's not a fixture, but called inside other fixtures."""
    return SlidingWindow(timedelta(hours=24), timedelta(minutes=1), window_limit=2000)


def new_win_10m_1s_wl1200_fl2():
    """It's not a fixture, but called inside other fixtures."""
    return SlidingWindow(timedelta(minutes=10), timedelta(seconds=1), window_limit=1200, frame_limit=2)
