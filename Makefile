.PHONY: help install db-up db-down db-logs migrate seed app api test paystack-check paystack-sync

PY := .venv/bin/python
PIP := .venv/bin/pip

help:
	@echo "Common dev tasks:"
	@echo "  make install         install python deps into .venv"
	@echo "  make db-up           start Postgres via docker-compose"
	@echo "  make db-down         stop Postgres"
	@echo "  make migrate         apply alembic migrations"
	@echo "  make seed            seed Free / Pro / Enterprise plans"
	@echo "  make app             run the Streamlit app on :8501"
	@echo "  make api             run the FastAPI service on :8000"
	@echo "  make test            run the full pytest suite"
	@echo "  make paystack-check  diagnose Paystack config and DB plans"
	@echo "  make paystack-sync   sync Paystack plan_codes into the DB by name"

install:
	$(PIP) install -e .

db-up:
	docker-compose up -d db

db-down:
	docker-compose down

db-logs:
	docker-compose logs -f db

migrate:
	.venv/bin/alembic upgrade head

seed:
	$(PY) -m app.db.seed

app:
	.venv/bin/streamlit run app/streamlit_app.py

api:
	.venv/bin/uvicorn api.main:app --reload --port 8000

test:
	.venv/bin/pytest tests/ -v

paystack-check:
	$(PY) -m app.paystack_check

paystack-sync:
	$(PY) -m app.paystack_sync_plans
