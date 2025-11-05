.PHONY: check coverage tox all

SHELL := /bin/bash

# Function to find the latest Python version for a given major.minor version
define find_python_version
$(shell \
	for search_dir in /usr/bin /usr/local/bin $$HOME/.asdf/installs/python/*/bin $$HOME/.pyenv/versions/*/bin /opt/python/*/bin; do \
		if [ -d "$$search_dir" ]; then \
			find "$$search_dir" -name "python$(1)*" -executable 2>/dev/null; \
		fi; \
	done | \
	grep -v -E "(venv|\.venv|config|gdb)" | \
	while read path; do \
		if [ -x "$$path" ]; then \
			version=$$("$$path" -c "import sys; print('.'.join(map(str, sys.version_info[:3])))" 2>/dev/null); \
			if [ "$$?" -eq 0 ] && echo "$$version" | grep -q "^$(1)\."; then \
				echo "$$version $$path"; \
			fi; \
		fi; \
	done | \
	sort -V | \
	tail -1 | \
	cut -d' ' -f2 \
)
endef

# Automatically detect Python versions 3.9-3.14
PYTHON_PATHS := \
	TOX_PY39_BASE=$(call find_python_version,3.9) \
	TOX_PY310_BASE=$(call find_python_version,3.10) \
	TOX_PY311_BASE=$(call find_python_version,3.11) \
	TOX_PY312_BASE=$(call find_python_version,3.12) \
	TOX_PY313_BASE=$(call find_python_version,3.13) \
	TOX_PY314_BASE=$(call find_python_version,3.14)

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

tox:
	@missing=""; \
	for pair in $(PYTHON_PATHS); do \
	  var=$${pair%%=*}; \
	  path=$${pair#*=}; \
	  if [ -n "$$path" ] && [ ! -x "$$path" ]; then \
	    missing="$$missing\n$$path"; \
	  elif [ -n "$$path" ]; then \
	    export $$var="$$path"; \
	  fi; \
	done; \
	if [ -n "$$missing" ]; then \
	  echo -e "The following required Python executables are missing or not executable:$$missing"; \
	  echo "Update the Makefile with correct paths for these executables and try again."; \
	  exit 1; \
	else \
	  deactivate 2>/dev/null || true; \
	  conda deactivate 2>/dev/null || true; \
	  docker compose down; \
	  docker compose up -d; \
	  tox -p; \
	  source .venv/bin/activate; \
	fi

all: check tox coverage
