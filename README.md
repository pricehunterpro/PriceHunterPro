# PriceHunter Pro

Initial project skeleton for the PriceHunter Pro platform.

## Included

- Docker Compose with Postgres, Redis, FastAPI backend, Celery workers, Angular frontend, and Nginx
- FastAPI application with JWT auth endpoints
- SQLAlchemy models and Alembic initial migration
- Falabella scraper skeleton
- Basic tests and CI workflow

## Quick start

1. Copy `.env.example` to `.env`
2. Run `docker compose up --build`
3. Open `http://localhost:8000/docs` for the API docs
