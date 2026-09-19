.PHONY: setup run test lint format typecheck check schema e2e build-mac build-win build-extension clean uninstall-mac
setup:
	uv sync
	uv run python scripts/setup.py
run:
	uv run privacy-guardian
test:
	uv run pytest --cov=privacy_guardian --cov-report=term-missing --cov-report=xml --cov-report=json --cov-fail-under=0
	uv run python tests/check_coverage.py coverage.json
lint:
	uv run ruff check .
	uv run ruff format --check .
format:
	uv run ruff check --fix .
	uv run ruff format .
typecheck:
	uv run mypy --strict src/
check: lint typecheck test
schema:
	uv run python scripts/generate_schema.py
e2e:
	uv run pytest tests/e2e -m e2e -v
build-extension: schema
	uv run python scripts/build_extension.py
build-mac:
	uv run python scripts/build.py mac
build-win:
	uv run python scripts/build.py windows
uninstall-mac:
	uv run python scripts/install.py uninstall
clean:
	uv run python scripts/clean.py
