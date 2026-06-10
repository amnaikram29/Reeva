.PHONY: install redis-up redis-down dev prod lint

install:
	pip install -r requirements.txt

redis-up:
	docker compose up -d redis

redis-down:
	docker compose down

dev:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

prod:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4

lint:
	ruff check app/
