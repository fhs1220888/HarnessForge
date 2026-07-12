# HarnessForge — common tasks. Run `make help` for the list.

.PHONY: help install test lint figures report replay-fails clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Editable install with dev deps
	pip install -e ".[dev]"

test: ## Run the test suite (no API key / Docker needed)
	pytest -q

lint: ## Ruff lint
	ruff check src tests

figures: ## Regenerate README figures from docs/data snapshots
	python scripts/make_figures.py

report: lint test figures ## Full local check: lint + tests + figures
	@echo "OK — lint clean, tests pass, figures regenerated."

replay-fails: ## Replay every failed run in RUN=<dir> (e.g. make replay-fails RUN=runs/tb_baseline)
	@test -n "$(RUN)" || (echo "set RUN=<run dir>"; exit 1)
	python -m harnessforge.replay --run-dir $(RUN) --grep max_steps

clean: ## Remove caches
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache
