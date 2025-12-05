import json
import random

from datetime import timedelta

import pytest

from call_gate import CallGate
from tests.parameters import GITHUB_ACTIONS_REDIS_TIMEOUT, create_call_gate, random_name, storages


@pytest.mark.timeout(GITHUB_ACTIONS_REDIS_TIMEOUT)
class TestSugar:
    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(("iterations", "value"), [(3, 5), (4, 2), (5, 3)])
    def test_decorator(self, storage, iterations, value):
        gate = create_call_gate(
            random_name(), timedelta(minutes=1), timedelta(seconds=1), frame_limit=10, storage=storage
        )

        @gate(value=value)
        def decorated():
            pass

        for _ in range(iterations):
            decorated()

        expected = iterations * value
        try:
            assert gate.sum == expected
        finally:
            gate.clear()

    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize(("iterations", "value"), [(3, 5), (4, 2), (5, 3)])
    def test_context_manager(self, storage, iterations, value):
        gate = create_call_gate(
            random_name(), timedelta(minutes=1), timedelta(seconds=1), frame_limit=10, storage=storage
        )

        for _ in range(iterations):
            with gate(value=value):
                pass

        expected = iterations * value
        try:
            assert gate.sum == expected
        finally:
            gate.clear()

    @pytest.mark.parametrize("storage", storages)
    @pytest.mark.parametrize("path_type", ["str", "path"])
    def test_file(self, storage, tmp_path, path_type):
        temp_dir = tmp_path / "file_tests"
        temp_file = temp_dir / f"{storage}_name.json"
        gate = CallGate(random_name(), timedelta(minutes=1), timedelta(seconds=1), frame_limit=30, storage=storage)
        try:
            for _ in range(random.randint(5, 10)):
                gate.update(value=random.randint(1, 5))

            storages_choices = ["simple", "shared", "redis"]

            state = gate.state
            name = gate.name
            old_current_dt = gate.current_dt
            old_storage = gate.storage

            if path_type == "str":
                temp_file = str(temp_file.absolute().resolve())

            gate.to_file(temp_file)
            with open(temp_file) as f:
                data = json.load(f)
                assert len(data["_data"]) == gate.frames
        finally:
            gate.clear()
            del gate

        new_storage = random.choice(storages_choices)
        while new_storage == old_storage:
            new_storage = random.choice(storages_choices)

        new_gate = CallGate.from_file(temp_file, storage=new_storage)
        try:
            assert new_gate.name == name
            assert new_gate.state == state
            assert new_gate.current_dt == old_current_dt
        finally:
            new_gate.clear()
