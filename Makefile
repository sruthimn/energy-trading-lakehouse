.PHONY: help setup test test-fast lint format

help:
	@echo "make setup      install the project and its tools"
	@echo "make test       run all tests (starts a small local Spark session)"
	@echo "make test-fast  run tests that do not need Spark"
	@echo "make lint       check the code style"
	@echo "make format     fix the code style automatically"

setup:
	python -m pip install --upgrade pip
	python -m pip install -e ".[dev]"
	pre-commit install

test:
	python -m pytest

test-fast:
	python -m pytest -m "not spark"

lint:
	ruff check .

format:
	ruff check --fix .
	ruff format .
