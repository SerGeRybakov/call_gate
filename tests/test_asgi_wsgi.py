import subprocess
import time

import httpx
import pytest


class TestASGI:
    @pytest.fixture(scope="function")
    def uvicorn_server(self):
        proc = subprocess.Popen(  # noqa: S603
            ["uvicorn", "tests.asgi_wsgi.asgi_app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]  # noqa: S607, S104
        )
        time.sleep(2)  # give the server time to start
        yield
        proc.terminate()
        proc.wait()

    @pytest.mark.parametrize(
        ("num_requests", "positive_case"),
        [
            # Positive case: number of requests within the limit - all responses should be 200
            (4, True),
            # Negative case: number of requests exceeds the limit - at least one 429 response is expected
            (20, False),
        ],
    )
    def test_asgi_web_server_rate_limit(self, uvicorn_server, num_requests, positive_case):
        responses = []
        with httpx.Client() as client:
            for _ in range(num_requests):
                response = client.get("http://0.0.0.0:8000/")
                responses.append(response.status_code)
                time.sleep(0.1)  # small delay between requests
        if positive_case:
            assert all(code == 200 for code in responses)
        else:
            assert any(code == 429 for code in responses)

    def test_hepercorn_server_fails(self):
        """Hypercorn fails.

        It spawns each worker as a daemon process, which is not allowed to have children subprocesses.
        """
        proc = subprocess.Popen(  # noqa: S603
            ["hypercorn", "tests.asgi_wsgi.asgi_app:app", "--bind", "0.0.0.0:8000", "--workers", "4"],  # noqa: S607
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(2)  # give the server time to start
        stderr_output = proc.stderr.read()
        proc.terminate()
        proc.wait()
        assert "AssertionError: daemonic processes are not allowed to have children" in stderr_output


class TestWSGI:
    @pytest.fixture(scope="function")
    def gunicorn_server(self):
        proc = subprocess.Popen(  # noqa: S603
            ["gunicorn", "tests.asgi_wsgi.wsgi_app:app", "--bind", "0.0.0.0:8100", "--workers", "4"]  # noqa: S607
        )
        time.sleep(2)  # give the server time to start
        yield
        proc.terminate()
        proc.wait()

    @pytest.mark.parametrize(
        ("num_requests", "positive_case"),
        [
            # Positive case: number of requests within the limit - all responses should be 200
            (4, True),
            # Negative case: number of requests exceeds the limit - at least one 429 response is expected
            (20, False),
        ],
    )
    def test_wsgi_web_server_rate_limit(self, gunicorn_server, num_requests, positive_case):
        responses = []
        with httpx.Client() as client:
            for _ in range(num_requests):
                response = client.get("http://0.0.0.0:8100/")
                responses.append(response.status_code)
                time.sleep(0.1)
        if positive_case:
            assert all(code == 200 for code in responses)
        else:
            assert any(code == 429 for code in responses)


if __name__ == "__main__":
    pytest.main()
