.PHONY: setup dev backend build run deploy migrate streamlit

setup:
	uv sync
	pnpm install --frozen-lockfile

dev:
	pnpm dev

backend:
	uv run uvicorn backend.app.main:app --reload --host 0.0.0.0 --port 8000

build:
	pnpm build

run: build
	uv run uvicorn backend.app.main:app --host 0.0.0.0 --port $${PORT:-8000}

deploy: build
	flyctl deploy

migrate:
	./scripts/apply-snowflake.sh

streamlit:
	./scripts/deploy-streamlit.sh
