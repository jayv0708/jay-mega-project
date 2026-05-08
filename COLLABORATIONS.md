# Collaborations

This repository was created with significant AI-assisted development.

## AI-assisted decisions

- Step 1 scaffold alignment: kept the existing service skeleton, added the spec-required `/log-ui` directory, and pointed Docker Compose at that path while leaving the pre-existing `log_ui` directory untouched to avoid destructive cleanup.
- Step 2 schema implementation: reconciled SQLAlchemy models and Alembic migration with the required PostgreSQL schema, including enum types, JSONB payloads, and environment-driven Alembic configuration.
- Step 3 context design: replaced the transitional context model with the requested SharedContext shape and implemented a per-agent ContextBudgetManager that triggers structured compression before logging policy violations.
- Step 4 agent design: implemented deterministic fallback behavior around Anthropic JSON calls so the orchestration path remains runnable without an API key while still using explicit model, temperature, and max_tokens when credentials are present.
- Step 5 tool design: kept fallback and retry behavior in Python code, added structured tool call logging, and used deterministic fixtures so tests are reproducible without live web or database services.
- Scaffold generation: initialized the monorepo structure, Docker Compose file, service Dockerfiles, and starter FastAPI/Flask application files.
- Dependency resolution: adjusted pinned dependency versions to the available packages on the environment.
- Directory restructuring: moved Alembic and database modules into `/db` and established `/agents`, `/tools`, and `/eval` packages.
- Prompt and tool scaffolding: created base classes and placeholder prompt files for future agent orchestration.

## Notes

All major decisions documented here are intended to make the implementation traceable and auditable.
