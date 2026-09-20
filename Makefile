.PHONY: db seed test dev-api dev-web types fixtures record-replay eval lint

db:
	docker compose up -d db

dev-api:
	cd backend && uvicorn app.main:app --reload

dev-web:
	cd frontend && npm run dev

test:
	cd backend && pytest

lint:
	cd backend && ruff check
	cd frontend && npm run lint
