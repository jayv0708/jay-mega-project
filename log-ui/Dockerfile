FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r requirements.txt
COPY log-ui ./log-ui
COPY db ./db
COPY alembic.ini ./alembic.ini
RUN useradd -m -u 1000 appuser && chown -R appuser /app
USER 1000
WORKDIR /app/log-ui
EXPOSE 8080
CMD ["python", "app.py"]
