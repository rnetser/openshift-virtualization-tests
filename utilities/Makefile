.PHONY: install test test-unit test-cov test-watch test-single test-parallel lint format clean help

UV_BIN ?= uv

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

install:  ## Install utilities with test dependencies
	$(UV_BIN) sync --extra test

test:  ## Run all tests
	$(UV_BIN) run pytest tests/

test-unit:  ## Run only unit tests
	$(UV_BIN) run pytest tests/ -m unit

test-cov:  ## Run tests with coverage report
	$(UV_BIN) run pytest tests/ --cov=. --cov-report=html --cov-report=term

test-watch:  ## Run tests in watch mode (requires pytest-watch)
	$(UV_BIN) run pytest-watch tests/

test-single:  ## Run a single test file (use TEST=test_architecture.py)
	$(UV_BIN) run pytest tests/$(TEST) -vv

test-parallel:  ## Run tests in parallel
	$(UV_BIN) run pytest tests/ -n auto

test-medium:  ## Run medium priority tests
	$(UV_BIN) run pytest tests/test_logger.py tests/test_os_utils.py tests/test_monitoring.py tests/test_hco.py tests/test_ssp.py -v

lint:  ## Run linting
	$(UV_BIN) run ruff check .
	$(UV_BIN) run ruff format --check .

format:  ## Format code
	$(UV_BIN) run ruff check --fix .
	$(UV_BIN) run ruff format .

clean:  ## Clean test artifacts
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .coverage
	rm -rf *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

pre-commit:  ## Run pre-commit checks
	$(UV_BIN) run pre-commit run --all-files
