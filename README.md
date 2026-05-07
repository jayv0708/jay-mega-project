# Jay Mega Project

## Phase 1 — Repo & Docker Scaffold

This repository contains a monorepo scaffold for a FastAPI-based API, an async worker, PostgreSQL database, and a lightweight log UI.

### Getting started

1. Install Docker Desktop and make sure Docker is running.
2. From the repository root, run:

```bash
docker compose up --build
```

3. Verify services:

- API: http://localhost:8000/
- Log UI: http://localhost:8080/
- PostgreSQL: port 5432

### What is included

- `docker-compose.yml` with four services: `api`, `worker`, `db`, `log-ui`
- `.env` for environment configuration
- `pyproject.toml` and `requirements.txt` with pinned versions
- Basic runnable skeletons for every service

### Notes

The current scaffold is a minimal starting point for Phase 2 and later work.
