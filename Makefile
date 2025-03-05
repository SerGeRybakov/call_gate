.PHONY: check coverage tox all

SHELL := /bin/bash

PYTHON_PATHS := \
	TOX_PY39_BASE=$(HOME)/.asdf/installs/python/3.9.21/bin/python \
	TOX_PY310_BASE=$(HOME)/.asdf/installs/python/3.10.16/bin/python \
	TOX_PY311_BASE=$(HOME)/.asdf/installs/python/3.11.11/bin/python \
	TOX_PY312_BASE=$(HOME)/.asdf/installs/python/3.12.9/bin/python \
	TOX_PY313_BASE=$(HOME)/.asdf/installs/python/3.13.2/bin/python

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
	@mypy ./call_gate --install-types

coverage:
	-@source .venv/bin/activate
	docker compose down
	docker compose up -d
	pytest --cov=./call_gate --cov-report=html --cov-report=term-missing --cov-branch
	@echo "Find html report at ./tests/code_coverage/index.html"

tox:
	@missing=""; \
	for pair in $(PYTHON_PATHS); do \
	  var=$${pair%%=*}; \
	  path=$${pair#*=}; \
	  if [ ! -x "$$path" ]; then \
	    missing="$$missing\n$$path"; \
	  else \
	    export $$var="$$path"; \
	  fi; \
	done; \
	if [ -n "$$missing" ]; then \
	  echo -e "The following required Python executables are missing or not executable:$$missing"; \
	  echo "Update the Makefile with correct paths for these executables and try again."; \
	  exit 1; \
	else \
	  tox -p; \
	fi

all: check tox coverage
