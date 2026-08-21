.PHONY: up down logs build test test-backend lint smoke demo fmt

up:            ## start the whole stack
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f backend frontend

test: test-backend lint

test-backend:
	docker compose run --rm backend pytest

lint:
	docker compose run --rm backend ruff check .
	cd frontend && npm run lint

fmt:
	docker compose run --rm backend ruff format .

smoke:
	python3 scripts/smoke_test.py

demo:
	python3 scripts/demo.py
