FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r requirements.txt
COPY api ./api
COPY app ./app
COPY agents ./agents
COPY tools ./tools
COPY eval ./eval
COPY db ./db
COPY retrieval ./retrieval
COPY job_queue ./job_queue
COPY alembic.ini ./alembic.ini
RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER 1000
ENV PYTHONPATH=/app
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

