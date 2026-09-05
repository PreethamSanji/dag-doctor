.PHONY: check fmt lint test test-unit test-integration eval eval-fast eval-injection index serve web web-build up down

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

eval:                     ## full golden set + threshold gate (calls an LLM)
	uv run triage eval

eval-fast:                ## random subset for local iteration; reports, does not gate
	uv run triage eval --fast

eval-injection:           ## adversarial subset only
	uv run triage eval --label injection

index:
	uv run triage index --rebuild

serve:                    ## dashboard API on :8000 (cards, feedback, /metrics)
	uv run triage serve

web:                      ## dashboard dev server on :5173, proxied to the API
	cd web && npm install && npm run dev

web-build:                ## typecheck + bundle the dashboard
	cd web && npm ci && npm run build

up:
	docker compose up -d

down:
	docker compose down
