.PHONY: install migrate run worker test lint docker-up docker-down

install:
	uv sync --all-extras

migrate:
	uv run alembic upgrade head

run:
	uv run uvicorn app.main:app --reload --port 8020

worker:
	uv run arq app.worker.WorkerSettings

test:
	uv run pytest -q

lint:
	uv run ruff check .

docker-up:
	docker compose up --build

docker-down:
	docker compose down
