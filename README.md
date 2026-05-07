# Real-Time Multi-Agent LLM Orchestration and Evaluation System

## Overview

This repository is a monorepo scaffold for a production-style LLM orchestration system using:
- Python 3.12
- FastAPI
- asyncio
- PostgreSQL
- SQLAlchemy + Alembic
- Docker Compose
- Server-Sent Events (SSE)

The project is organized for clear separation of concerns:
- `/api` — FastAPI application
- `/worker` — background job processor
- `/agents` — agent classes and prompt definitions
- `/tools` — runtime tool implementations
- `/eval` — evaluation harness and case fixtures
- `/db` — Alembic migrations and SQLAlchemy models
- `/log-ui` — lightweight log query interface

## One-command setup

Copy `.env.example` to `.env`, then start all services:

```bash
cp .env.example .env && docker compose up --build
```

On Windows PowerShell:

```powershell
copy .env.example .env
docker compose up --build
```

## Services

- `api`: FastAPI app exposed on port `8000`
- `worker`: asynchronous background processor
- `db`: PostgreSQL 15 database
- `log-ui`: lightweight log/query UI exposed on port `8080`

## Current scaffold

- `docker-compose.yml` with API, worker, db, and log-ui services
- `.env.example` with all runtime configuration variables
- `pyproject.toml` and `requirements.txt` with pinned dependencies
- `/agents` and `/tools` packages for future agent/tool logic
- `/db` package with Alembic migrations and SQLAlchemy models
- `/eval/cases` placeholder directory for evaluation fixtures
- `COLLABORATIONS.md` for documenting AI-assisted decisions

## Next steps

This initial scaffold completes Step 1. The next work will implement:
1. database schema and migrations
2. shared context object and budget manager
3. agent orchestration and SSE streaming
4. tool execution logging and evaluation pipeline

## Notes

This repository is intentionally structured for incremental delivery and stepwise completion of the full orchestration system.
