.PHONY: check fmt lint test test-unit test-integration eval index up down

check: lint test          ## same gate as CI: lint + unit + fixture tests

fmt:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check .
	uv run ruff check .

test:
	uv run pytest -m "not llm"

test-unit:
	uv run pytest tests/unit -m "not llm"

test-integration:
	uv run pytest tests/integration -m "not llm"

eval:
	uv run triage eval

index:
	uv run triage index --rebuild

up:
	docker compose up -d

down:
	docker compose down
