.PHONY: up down logs build test test-backend test-migrations lint smoke demo fmt migrate

up:            ## start the whole stack
	docker compose up --build -d

down:
	docker compose down

logs:
	docker compose logs -f backend frontend

test: test-backend lint

test-backend:
	docker compose exec -T backend pytest

# The rest of the suite runs on SQLite. This runs the migrations for real, on a
# scratch Postgres database that is created and dropped around each test.
test-migrations:
	docker compose exec -T \
	  -e MIGRATION_TEST_URL=postgresql://admin:password@db:5432/agent_db \
	  backend pytest -q tests/test_migrations.py

migrate:
	docker compose exec -T backend alembic upgrade head

lint:
	docker compose run --rm backend ruff check .
	cd frontend && npm run lint

fmt:
	docker compose run --rm backend ruff format .

smoke:
	python3 scripts/smoke_test.py

demo:
	python3 scripts/demo.py
