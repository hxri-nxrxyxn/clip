.PHONY: test lint type coverage fmt clean check

PYTHON := .venv/bin/python
PYTEST := .venv/bin/pytest
RUFF := .venv/bin/ruff
MYPY := .venv/bin/mypy

test:
	$(PYTEST) tests/

coverage:
	$(PYTEST) --cov=app --cov=2-transcribe/scripts --cov-report=term-missing tests/

lint:
	$(RUFF) check app tests

fmt:
	$(RUFF) format app tests
	$(RUFF) check --fix app tests

type:
	$(MYPY) app

check: lint type test
