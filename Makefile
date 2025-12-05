.PHONY: check coverage tox all test-cluster test-cluster-all test-cluster-3.10 test-cluster-3.11 test-cluster-3.12 test-cluster-3.13 test-cluster-3.14

SHELL := /bin/bash

run_test = \
	echo "======= TEST $(1) ======="; \
	deactivate; \
	source $(2)/bin/activate; \
	docker compose down; \
	docker compose up -d; \
	sleep 10; \
	pytest; \
	docker compose down

run_cluster_test = \
	echo "======= CLUSTER TEST $(1) ======="; \
	deactivate; \
	source $(2)/bin/activate; \
	docker compose down; \
	docker compose up -d; \
	sleep 10; \
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
	sleep 10
	pytest --cov=./call_gate --cov-report=html --cov-report=term-missing --cov-branch --ignore=tests/test_asgi_wsgi.py --ignore=tests/test_redis_cluster.py --ignore=tests/cluster/
	@echo "Find html report at ./tests/code_coverage/index.html"


all: check coverage tox
