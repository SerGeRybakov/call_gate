import subprocess
import time

import httpx
import pytest


try:
    from importlib.metadata import version

    HYPERCORN_VERSION = tuple(map(int, version("hypercorn").split(".")))
except (ImportError, Exception):
    HYPERCORN_VERSION = (0, 0, 0)


def terminate_process(proc: subprocess.Popen, timeout: float = 5.0) -> None:
    """Safely terminate a subprocess with timeout.

    First tries terminate(), then kill() if process doesn't exit within timeout.
    This prevents hanging tests in Python 3.12+ where subprocess.wait() can hang.

    :param proc: The subprocess to terminate.
    :param timeout: Maximum time to wait for process to terminate (default: 5 seconds).
    """
    if proc.poll() is not None:
        return  # Process already terminated

    proc.terminate()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        # Force kill if terminate didn't work
        proc.kill()
        proc.wait()  # Wait for kill to complete


class TestASGIUvicorn:
    @pytest.fixture(scope="function")
    def uvicorn_server(self):
        proc = subprocess.Popen(
            ["uvicorn", "tests.asgi_wsgi.asgi_app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]  # noqa: S104
        )
        time.sleep(2)  # give the server time to start
        yield
        terminate_process(proc)

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


class TestASGIHypercorn:
    @pytest.mark.parametrize(
        ("use_no_daemon", "expected_to_fail"),
        [
            # Test daemon mode (should fail with daemon error)
            (False, True),
            # Test non-daemon mode (should work without daemon error)
            pytest.param(
                True,
                False,
                marks=pytest.mark.xfail(
                    HYPERCORN_VERSION >= (0, 18, 0), reason="daemon=false config added in Hypercorn 0.18.0+"
                ),
                id="no_daemon_mode",
            ),
        ],
        ids=["daemon_mode", None],  # None because no_daemon_mode has its own id
    )
    def test_hypercorn_server_daemon_behavior(self, use_no_daemon, expected_to_fail):
        """Test Hypercorn daemon behavior with and without daemon=false config.

        - daemon_mode: Should fail with daemon process error
        - no_daemon_mode: Should work without daemon process error (if supported)
        """
        # Apply conditional xfail based on version and parameters
        if use_no_daemon and HYPERCORN_VERSION >= (0, 18, 0):
            pytest.xfail("--no-daemon behavior may be unstable in Hypercorn 0.18.0+")

        cmd = ["hypercorn", "tests.asgi_wsgi.asgi_app:app", "--bind", "0.0.0.0:8000", "--workers", "4"]

        if use_no_daemon:
            # daemon=false config only available in Hypercorn 0.18.0+
            if HYPERCORN_VERSION < (0, 18, 0):
                pytest.skip("daemon config not available in Hypercorn < 0.18.0")
            cmd.extend(["--config", "/dev/stdin"])

            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            proc.stdin.write("daemon = false\n")
            proc.stdin.close()
        else:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        time.sleep(2)  # give the server time to start
        stderr_output = proc.stderr.read()
        terminate_process(proc)

        daemon_error_present = "AssertionError: daemonic processes are not allowed to have children" in stderr_output

        if expected_to_fail:
            assert daemon_error_present, "Expected daemon process error but didn't find it"
        else:
            assert not daemon_error_present, f"Unexpected daemon process error: {stderr_output}"

    @pytest.fixture(scope="function")
    def hypercorn_server_no_daemon(self):
        """Hypercorn server fixture without daemon mode (default behavior in Hypercorn >=0.18.0)."""
        proc = subprocess.Popen(
            [
                "hypercorn",
                "tests.asgi_wsgi.asgi_app:app",
                "--bind",
                "0.0.0.0:8001",
                "--workers",
                "4",
                "--config",
                "/dev/stdin",
            ],
            stdin=subprocess.PIPE,
            text=True,
        )
        proc.stdin.write("daemon = false\n")
        proc.stdin.close()
        time.sleep(2)  # give the server time to start
        yield
        terminate_process(proc)

    @pytest.mark.parametrize(
        ("num_requests", "positive_case"),
        [
            # Positive case: number of requests within the limit - all responses should be 200
            (4, True),
            # Negative case: number of requests exceeds the limit - at least one 429 response is expected
            (20, False),
        ],
    )
    @pytest.mark.skipif(
        HYPERCORN_VERSION < (0, 18, 0), reason="Hypercorn before 0.18.0 has no option to switch off daemon mode"
    )
    def test_hypercorn_no_daemon_rate_limit(self, hypercorn_server_no_daemon, num_requests, positive_case):
        """Test rate limiting with Hypercorn server using --no-daemon flag."""
        responses = []
        with httpx.Client() as client:
            for _ in range(num_requests):
                response = client.get("http://0.0.0.0:8001/")
                responses.append(response.status_code)
                time.sleep(0.1)  # small delay between requests
        if positive_case:
            assert all(code == 200 for code in responses)
        else:
            assert any(code == 429 for code in responses)


class TestWSGI:
    @pytest.fixture(scope="function")
    def gunicorn_server(self):
        proc = subprocess.Popen(
            ["gunicorn", "tests.asgi_wsgi.wsgi_app:app", "--bind", "0.0.0.0:8100", "--workers", "4"]
        )
        time.sleep(2)  # give the server time to start
        yield
        terminate_process(proc)

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
