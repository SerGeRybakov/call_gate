.PHONY: check coverage tox all test-cluster test-cluster-all test-cluster-3.10 test-cluster-3.11 test-cluster-3.12 test-cluster-3.13 test-cluster-3.14

SHELL := /bin/bash

help:
	@echo "Available targets:"
	@echo "  check - Run code quality checks (sort, format, lint, mypy)"
	@echo "  coverage - Run tests with coverage report"
	@echo "  tox - Run all tests across multiple Python versions"
	@echo "  test - Run tests with default Python version"
	@echo "  test-3.10 - Run tests with Python 3.10"
	@echo "  test-3.11 - Run tests with Python 3.11"
	@echo "  test-3.12 - Run tests with Python 3.12"
	@echo "  test-3.13 - Run tests with Python 3.13"
	@echo "  test-3.14 - Run tests with Python 3.14"
	@echo "  test-cluster - Run cluster tests with default Python version"
	@echo "  test-cluster-3.10 - Run cluster tests with Python 3.10"
	@echo "  test-cluster-3.11 - Run cluster tests with Python 3.11"
	@echo "  test-cluster-3.12 - Run cluster tests with Python 3.12"
	@echo "  test-cluster-3.13 - Run cluster tests with Python 3.13"
	@echo "  test-cluster-3.14 - Run cluster tests with Python 3.14"
	@echo "  test-cluster-all - Run all cluster tests across multiple Python versions"
	@echo "  all - Run all checks and tests"

run_test = \
	echo "======= TEST $(1) ======="; \
	deactivate; \
	source $(2)/bin/activate; \
	docker compose down; \
	docker compose up -d; \
	sleep 15; \
	pytest; \
	docker compose down

run_cluster_test = \
	echo "======= CLUSTER TEST $(1) ======="; \
	deactivate; \
	source $(2)/bin/activate; \
	docker compose down; \
	docker compose up -d; \
	sleep 15; \
	pytest -m cluster tests/test_redis_cluster.py -v; \
	docker compose down

test:
	$(call run_test,3.9,.venv)
test-3.10:
	$(call run_test,3.10,.venv-3.10)
test-3.11:
	$(call run_test,3.11,.venv-3.11)
test-3.12:
	$(call run_test,3.12,.venv-3.12)
test-3.13:
	$(call run_test,3.13,.venv-3.13)
test-3.14:
	$(call run_test,3.14,.venv-3.14)

tox: test test-3.10 test-3.11 test-3.12 test-3.13 test-3.14

# Cluster test targets
test-cluster:
	$(call run_cluster_test,3.9,.venv)
test-cluster-3.10:
	$(call run_cluster_test,3.10,.venv-3.10)
test-cluster-3.11:
	$(call run_cluster_test,3.11,.venv-3.11)
test-cluster-3.12:
	$(call run_cluster_test,3.12,.venv-3.12)
test-cluster-3.13:
	$(call run_cluster_test,3.13,.venv-3.13)
test-cluster-3.14:
	$(call run_cluster_test,3.14,.venv-3.14)

test-cluster-all: test-cluster test-cluster-3.10 test-cluster-3.11 test-cluster-3.12 test-cluster-3.13 test-cluster-3.14

check:
	-@source .venv/bin/activate
	@echo "======= SSORT ======="
	@ssort ./call_gate
	@echo "======= RUFF FORMAT ======="
	@ruff format ./call_gate
	@ruff format ./tests
	@echo "======= RUFF LINT ======="
	@ruff check ./call_gate --fix
	@ruff check ./tests --fix
	@echo "======= MYPY ======="
	@mypy ./call_gate --install-types --non-interactive

coverage:
	-@source .venv/bin/activate
	docker compose down
	docker compose up -d
	sleep 15
	pytest -m "not cluster" --cov=./call_gate --cov-branch --cov-report=xml --ignore=tests/test_asgi_wsgi.py --ignore=tests/cluster/ ./tests --retries=3
	@echo "Find html report at ./tests/code_coverage/index.html"


all: check coverage tox
