_default:
    just --list

venv:
    uv sync

pre-commit: 
    uv sync
    uv run ruff format .
    uv run ruff check .
    uv run pyright .

ci-setup:
    pip install uv
    uv sync

ci-check:
    uv run ruff format --check .
    uv run ruff check .
    uv run pyright .

clean:
	@rm -rf .venv/
	@rm -rf .mypy_cache/
	@rm -rf .pytest_cache/
	@rm -rf .ruff_cache/
	@rm -rf dagster_uc.egg-info/
