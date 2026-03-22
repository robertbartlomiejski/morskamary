.PHONY: help install test cov fmt lint qa clean

PY ?= python3
PKG = src

help:
	@echo "Available targets:"
	@echo "  install  Install package with dev extras"
	@echo "  test     Run all tests with verbose output"
	@echo "  cov      Run tests with coverage report"
	@echo "  fmt      Format code (black + isort)"
	@echo "  lint     Lint code (flake8)"
	@echo "  qa       Run fmt + lint + test in sequence"
	@echo "  clean    Remove build/cache artifacts"

install:
	$(PY) -m pip install -e ".[dev]"

test:
	$(PY) -m pytest tests/ -v --tb=short

cov:
	$(PY) -m pytest tests/ -v --tb=short --cov=$(PKG) --cov-report=term-missing

fmt:
	$(PY) -m black $(PKG) tests/
	$(PY) -m isort $(PKG) tests/

lint:
	$(PY) -m flake8 $(PKG) tests/

qa: fmt lint test

clean:
	rm -rf .pytest_cache .mypy_cache build dist *.egg-info .coverage htmlcov __pycache__
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
