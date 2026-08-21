.PHONY: up down logs build test test-backend lint smoke fmt

up:            ## start the whole stack
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f backend frontend

test: test-backend lint

test-backend:
	cd backend && pytest

lint:
	cd frontend && npm run lint
	cd backend && ruff check .

smoke:
	python3 scripts/smoke_test.py
