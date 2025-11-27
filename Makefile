.PHONY: check coverage tox all

SHELL := /bin/bash

run_test = \
	echo "======= TEST $(1) ======="; \
	deactivate; \
	source $(2)/bin/activate; \
	docker compose down; \
	docker compose up -d; \
	pytest; \
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
	pytest --cov=./call_gate --cov-report=html --cov-report=term-missing --cov-branch
	@echo "Find html report at ./tests/code_coverage/index.html"


all: check coverage tox
