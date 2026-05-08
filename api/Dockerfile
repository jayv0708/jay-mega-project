FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY api ./api
COPY app ./app
COPY agents ./agents
COPY tools ./tools
COPY eval ./eval
COPY db ./db
COPY alembic.ini ./alembic.ini
RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER 1000
WORKDIR /app/api
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
