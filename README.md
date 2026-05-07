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
- `alembic/` migration scaffold and initial schema metadata in `app/models.py`

### Phase 2 setup

After starting the database, run:

```bash
export ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres:postgres@db:5432/appdb
alembic upgrade head
```

On Windows PowerShell use:

```powershell
$env:ALEMBIC_DATABASE_URL = 'postgresql+psycopg://postgres:postgres@db:5432/appdb'
alembic upgrade head
```

### Notes

The current scaffold is a minimal starting point for Phase 2 and later work.
